from ..shared.auth import token_for


def run_charge() -> str:
    return f"charged:{token_for('billing')}"
