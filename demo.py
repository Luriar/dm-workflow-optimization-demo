"""New, independent offline demonstration. No Instagram/network calls."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Contact:
    code: str
    opted_in: bool = False

def prepare_batch(contacts, suppressed=()):
    """Create a unique contact queue; require opt-in and exclude suppression list."""
    blocked = set(suppressed)
    seen = set()
    queue = []
    for item in contacts:
        if item.code in seen or not item.opted_in or item.code in blocked:
            continue
        seen.add(item.code)
        queue.append(item.code)
    return queue

def simulate_delivery(queue, fail_once=()):
    """Return an audit trail for a simulated transport; sends nothing."""
    failed = set(fail_once)
    events = []
    for code in queue:
        if code in failed:
            events.append((code, "retry_scheduled"))
        else:
            events.append((code, "simulated_success"))
    return events

if __name__ == "__main__":
    contacts = [Contact("fictional-A", True), Contact("fictional-B", False),
                Contact("fictional-A", True), Contact("fictional-C", True)]
    print(simulate_delivery(prepare_batch(contacts, {"fictional-C"}), {"fictional-A"}))
