"""Command-driven chat interface for the Drafting and Scanner agents."""

from __future__ import annotations

from app.agent_runtime import create_default_state, handle_cli_message


def main() -> None:
    print("DocFlow Agent Console")
    print("Commands: /draft, /scan, /rag, /query")
    state = create_default_state()
    while True:
        try:
            user_input = input("\n> ").strip()
        except KeyboardInterrupt:
            print("\nGoodbye.")
            break
        if not user_input:
            continue
        result = handle_cli_message(user_input, state)
        print(result["response"])
        state = result["state"]


if __name__ == "__main__":
    main()
