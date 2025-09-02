#! /usr/bin/env python3
# set endoding: utf-8
# set language: en_US.UTF-8

import os
import asyncio
import subprocess
import urllib3
import re
import sys
import termios
import tty
from typing import List, Tuple
from kubernetes.client import V1Pod
from kubernetes import client, config
from pydantic import BaseModel
from typing import Literal, Optional, Union
from pydantic_ai import Agent
from dotenv import load_dotenv

# Disable urllib3 SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load environment variables from .env file
load_dotenv()
if not os.environ.get("OPENAI_API_KEY"):
    raise ValueError("OPENAI_API_KEY environment variable is required")
else:
    print("OPENAI_API_KEY environment variable is set")


# ----------------------------
# Pydantic models
# ----------------------------
class ActionRequest(BaseModel):
    type: Literal[
        "DESCRIBE_POD",
        "LOGS",
        "DESCRIBE_DEPLOYMENT",
        "GET_CONFIGMAP",
        "GET_EVENTS",
        "STOP",
    ]
    namespace: Optional[str] = None
    name: Optional[str] = None


class FinalAnalysis(BaseModel):
    root_cause: str
    remediation: str


AgentResponse = Union[ActionRequest, FinalAnalysis]


# ----------------------------
# K8s helpers
# ----------------------------
def init_k8s() -> None:
    """Initialize Kubernetes client configuration.

    Attempts to load local kubeconfig first; if unavailable, falls back to
    in-cluster configuration (for when running inside a Kubernetes Pod).
    """
    try:
        config.load_kube_config()
    except:
        config.load_incluster_config()


def run_cmd(cmd: List[str]) -> str:
    """Execute a shell command and return its stdout as text.

    Args:
        cmd: Command and arguments as a list, e.g. ["kubectl", "get", "pods"].

    Returns:
        Command output as a string. On failure, returns a formatted error message.
    """
    try:
        return subprocess.check_output(cmd, text=True)
    except subprocess.CalledProcessError as e:
        return f"❌ Error executing {' '.join(cmd)}:\n{e.output}"


def resolve_controller_for_pod(pod: V1Pod) -> Tuple[Optional[str], Optional[str]]:
    """Resolve the higher-level controller that manages a Pod.

    Resolves common ownership chains such as ReplicaSet→Deployment, and returns
    direct controllers for StatefulSet, DaemonSet, and Job.

    Args:
        pod: A V1Pod object.

    Returns:
        Tuple of (kind, name) for the controller, or (None, None) if unknown.
    """
    try:
        apps_v1 = client.AppsV1Api()
        batch_v1 = client.BatchV1Api()
        owner_refs = pod.metadata.owner_references or []
        controller_ref = None
        for ref in owner_refs:
            if getattr(ref, "controller", False):
                controller_ref = ref
                break
        if controller_ref is None and owner_refs:
            controller_ref = owner_refs[0]

        if not controller_ref:
            return (None, None)

        kind = controller_ref.kind
        name = controller_ref.name
        namespace = pod.metadata.namespace

        if kind == "ReplicaSet":
            try:
                rs = apps_v1.read_namespaced_replica_set(name=name, namespace=namespace)
                rs_owners = rs.metadata.owner_references or []
                for ref in rs_owners:
                    if getattr(ref, "controller", False) and ref.kind == "Deployment":
                        return ("Deployment", ref.name)
                return ("ReplicaSet", name)
            except Exception:
                return ("ReplicaSet", name)

        if kind in ("StatefulSet", "DaemonSet"):
            return (kind, name)

        if kind == "Job":
            try:
                job = batch_v1.read_namespaced_job(name=name, namespace=namespace)
                job.metadata  # touch to ensure fetched
                return ("Job", name)
            except Exception:
                return ("Job", name)

        return (kind, name)
    except Exception:
        return (None, None)


def get_failing_pods(
    namespace: Optional[str] = None,
) -> List[Tuple[str, str, str, Optional[str], Optional[str]]]:
    """List pods that are not Ready across selected namespace or all namespaces.

    Determines non-ready pods via the Pod Ready condition, deriving a reason
    from the condition, container states, or pod phase. Excludes pods with
    reason "PodCompleted".

    Returns:
        A list of tuples: (namespace, name, reason, controller_kind, controller_name).
    """
    v1 = client.CoreV1Api()
    if namespace:
        pods = v1.list_namespaced_pod(namespace=namespace, watch=False)
    else:
        pods = v1.list_pod_for_all_namespaces(watch=False)
    not_ready = []
    for pod in pods.items:
        ready_condition = None
        for condition in pod.status.conditions or []:
            if condition.type == "Ready":
                ready_condition = condition
                break

        is_ready = (
            ready_condition is not None
            and getattr(ready_condition, "status", None) == "True"
        )

        if not is_ready:
            reason = None

            if ready_condition is not None:
                reason = getattr(ready_condition, "reason", None) or getattr(
                    ready_condition, "message", None
                )

            if not reason:
                container_reasons = []
                for cs in pod.status.container_statuses or []:
                    state = getattr(cs, "state", None)
                    if not state:
                        continue
                    waiting = getattr(state, "waiting", None)
                    terminated = getattr(state, "terminated", None)
                    if waiting and getattr(waiting, "reason", None):
                        container_reasons.append(waiting.reason)
                    if terminated and getattr(terminated, "reason", None):
                        container_reasons.append(terminated.reason)
                if container_reasons:
                    reason = ", ".join(sorted(set(container_reasons)))

            if not reason:
                reason = pod.status.phase or "NotReady"

            # Exclude completed pods from reporting
            if reason == "PodCompleted":
                continue

            controller_kind, controller_name = resolve_controller_for_pod(pod)
            not_ready.append(
                (
                    pod.metadata.namespace,
                    pod.metadata.name,
                    reason,
                    controller_kind,
                    controller_name,
                )
            )

    return not_ready


# ----------------------------
# Agent setup
# ----------------------------
agent = Agent[AgentResponse](
    model="gpt-4o",  # Updated to a valid model name
    output_type=AgentResponse,
    system_prompt="""
You are a Kubernetes debugging assistant in an interactive CLI.
You can:
- Answer user questions conversationally
- Request more info by returning ActionRequest
- Or conclude with FinalAnalysis

Always return JSON that matches the schema.
""",
)


# ----------------------------
# Chat loop
# ----------------------------
async def chat_loop(
    ns: str,
    pod: str,
    reason: str,
    all_pods: List[Tuple[str, str, str, Optional[str], Optional[str]]],
) -> None:
    """Interactive debugging loop for a selected pod.

    Shows prompts, accepts user input, switches pods with Ctrl+n, and calls
    the language model to produce actions or analyses. Executes cluster actions
    like describe/logs/events on demand and streams results back into context.

    Args:
        ns: Namespace of the selected pod.
        pod: Name of the selected pod.
        reason: Brief reason the pod is not ready.
        all_pods: List of failing pod tuples to allow switching.
    """
    context = f"Pod {pod} in namespace {ns} is failing: {reason}"
    print("\n💬 Interactive Debugging Session Started")
    print("Type 'exit' to quit. Press CTRL+n to switch to next pod.\n")

    def read_user_input_or_ctrl_n(prompt: str) -> Tuple[str, bool]:
        """Read a line of input or detect Ctrl+n.

        Returns a tuple (text, is_ctrl_n). When Ctrl+n is pressed, text is
        an empty string and is_ctrl_n is True. Otherwise, returns the typed
        text with is_ctrl_n False.
        """
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            buffer = []
            sys.stdout.write(prompt)
            sys.stdout.flush()
            while True:
                ch = sys.stdin.read(1)
                if ch == "\x0e":  # CTRL+n
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return ("", True)
                if ch in ("\r", "\n"):
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return ("".join(buffer).strip(), False)
                if ch == "\x7f":  # Backspace
                    if buffer:
                        buffer.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                # Basic printable range; skip other control chars
                if "\x20" <= ch <= "\x7e":
                    buffer.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    # Track current selection index for CTRL+n cycling
    try:
        current_idx = next(
            i
            for i, t in enumerate(all_pods)
            if t[0] == ns and t[1] == pod and t[2] == reason
        )
    except StopIteration:
        current_idx = 0

    while True:
        user_input, ctrl_n = read_user_input_or_ctrl_n("👤 You: ")
        if ctrl_n:
            current_idx = (current_idx + 1) % len(all_pods)
            ns, pod, reason = all_pods[current_idx][0:3]
            context = f"Pod {pod} in namespace {ns} is failing: {reason}"
            print(f"\n🔄 Switched to pod {pod} (ns={ns}, reason={reason})")
            continue
        user_input = user_input.strip()
        if user_input.lower() in ["exit", "quit"]:
            print("👋 Exiting debugger.")
            break

        # Deprecated switching via text command remains for compatibility
        if user_input.startswith("switch"):
            try:
                idx = int(user_input.split()[1]) - 1
                if 0 <= idx < len(all_pods):
                    current_idx = idx
                    ns, pod, reason = all_pods[current_idx][0:3]
                    context = f"Pod {pod} in namespace {ns} is failing: {reason}"
                    print(f"\n🔄 Switched to pod {pod} (ns={ns}, reason={reason})")
                    continue
                else:
                    print("❌ Invalid choice, try again.")
                    continue
            except Exception:
                print("❌ Invalid switch command. Use 'switch <number>'.")
                continue

        # Combine pod context + user input
        user_prompt = f"{context}\nUser: {user_input}"

        try:
            run_output = await agent.run(user_prompt=user_prompt)
        except Exception as e:
            print(f"\n❌ Error from model: {e}")
            continue

        # Prefer the structured output if available
        result = getattr(run_output, "output", None)
        if result is None:
            result = getattr(run_output, "data", None)
        if result is None:
            result = run_output

        if isinstance(result, ActionRequest):
            print(f"\n🤖 OpenAI requests action: {result}")

            if result.type == "STOP":
                print("🛑 OpenAI requested to stop.")
                return

            # Execute action
            if result.type == "DESCRIBE_POD":
                output = run_cmd(
                    [
                        "kubectl",
                        "describe",
                        "pod",
                        result.name,
                        "-n",
                        result.namespace,
                    ]
                )
            elif result.type == "LOGS":
                target_namespace = result.namespace or ns
                target_pod = result.name or pod

                selected_container = None
                try:
                    v1 = client.CoreV1Api()
                    pod_obj = v1.read_namespaced_pod(
                        name=target_pod, namespace=target_namespace
                    )

                    container_names = []
                    if getattr(pod_obj.spec, "init_containers", None):
                        container_names.extend(
                            [
                                c.name
                                for c in pod_obj.spec.init_containers
                                if c and getattr(c, "name", None)
                            ]
                        )
                    if getattr(pod_obj.spec, "containers", None):
                        container_names.extend(
                            [
                                c.name
                                for c in pod_obj.spec.containers
                                if c and getattr(c, "name", None)
                            ]
                        )

                    unique_names = list(dict.fromkeys(container_names))
                    if len(unique_names) > 1:
                        print("\nMultiple containers detected in pod. Select one:")
                        for idx, cname in enumerate(unique_names, 1):
                            print(f"{idx}. {cname}")
                        while True:
                            try:
                                choice = int(input("Select a container (number): ")) - 1
                                if 0 <= choice < len(unique_names):
                                    selected_container = unique_names[choice]
                                    break
                                else:
                                    print("❌ Invalid choice, try again.")
                            except ValueError:
                                print("❌ Please enter a number.")
                    elif len(unique_names) == 1:
                        selected_container = unique_names[0]
                except Exception as e:
                    print(f"⚠️ Could not enumerate containers: {e}")

                cmd = [
                    "kubectl",
                    "logs",
                    target_pod,
                    "-n",
                    target_namespace,
                    "--tail=100",
                ]
                if selected_container:
                    cmd.extend(["-c", selected_container])

                output = run_cmd(cmd)
            elif result.type == "DESCRIBE_DEPLOYMENT":
                output = run_cmd(
                    [
                        "kubectl",
                        "describe",
                        "deployment",
                        result.name,
                        "-n",
                        result.namespace,
                    ]
                )
            elif result.type == "GET_CONFIGMAP":
                output = run_cmd(
                    [
                        "kubectl",
                        "get",
                        "configmap",
                        result.name,
                        "-n",
                        result.namespace,
                        "-o",
                        "yaml",
                    ]
                )
            elif result.type == "GET_EVENTS":
                output = run_cmd(["kubectl", "get", "events", "-n", result.namespace])
            else:
                output = f"⚠️ Unknown action: {result.type}"

            # print(f"\n📡 Cluster output for {result.type}:\n{output[:800]}...\n")
            print(f"\n📡 Cluster output for {result.type}:\n{output}...\n")
            context += f"\n\n# Result of {result.type} ({result.namespace}/{result.name})\n{output}\n"

        elif isinstance(result, FinalAnalysis):
            print("\n✅ Final Analysis:")
            print(f"Root Cause: {result.root_cause}")

            def _format_bullets(text: str) -> str:
                try:
                    # Insert newline before '-', '*', '•', or numbered bullets when not at start of line
                    text = re.sub(r"(?<!^)(?<!\n)([-•*]\s+)", r"\n\1", text)
                    text = re.sub(r"(?<!^)(?<!\n)(\d+\.\s+)", r"\n\1", text)
                except Exception:
                    pass
                return text

            formatted_remediation = _format_bullets(result.remediation)
            print(f"Remediation:\n{formatted_remediation}\n")
            context += f"\n\n# Final Analysis\nRoot Cause: {result.root_cause}\nRemediation:\n{formatted_remediation}\n"
        else:
            text = getattr(run_output, "output_text", None)
            if not text:
                # If the model returned a Pydantic object, pretty-print as JSON
                try:
                    if hasattr(result, "model_dump_json"):
                        text = result.model_dump_json(indent=2)
                    elif hasattr(result, "model_dump"):
                        import json as _json

                        text = _json.dumps(result.model_dump(), indent=2)
                except Exception:
                    pass
            if not text:
                text = str(result)
            print(f"\n📝 Model response:\n{text}\n")
            context += f"\n\n# Model Response\n{text}\n"


# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    init_k8s()
    # List namespaces and prompt selection
    v1_ns = client.CoreV1Api()
    try:
        ns_list = v1_ns.list_namespace()
        namespaces = sorted([item.metadata.name for item in ns_list.items])
    except Exception:
        namespaces = []

    selected_ns = None
    if namespaces:
        print("\n📁 Available namespaces:")
        print("0. All namespaces")
        for i, ns_name in enumerate(namespaces, 1):
            print(f"{i}. {ns_name}")
        while True:
            try:
                choice = input("\nSelect a namespace (number, 0 for all): ").strip()
                if choice == "":
                    # default to all
                    break
                idx = int(choice)
                if idx == 0:
                    break
                if 1 <= idx <= len(namespaces):
                    selected_ns = namespaces[idx - 1]
                    break
                else:
                    print("❌ Invalid choice, try again.")
            except ValueError:
                print("❌ Please enter a number.")
            except EOFError:
                break

    failing_pods = get_failing_pods(selected_ns)

    if not failing_pods:
        print("✅ No failing pods detected.")
    else:
        print("\n🚨 Failing pods detected:")
        for i, (ns, pod, reason, ctrl_kind, ctrl_name) in enumerate(failing_pods, 1):
            ctrl_info = f", {ctrl_kind}={ctrl_name}" if ctrl_kind and ctrl_name else ""
            print(f"{i}. {pod} (ns={ns}, reason={reason}{ctrl_info})")

        while True:
            try:
                choice = int(input("\nSelect a pod to debug (number): "))
                if 1 <= choice <= len(failing_pods):
                    ns, pod, reason, ctrl_kind, ctrl_name = failing_pods[choice - 1]
                    asyncio.run(chat_loop(ns, pod, reason, failing_pods))
                    break
                else:
                    print("❌ Invalid choice, try again.")
            except ValueError:
                print("❌ Please enter a number.")
