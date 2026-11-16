"""
Minimal example using AIBasedDecisionEngine (default behavior)
"""
import time
from nexus_proactive_when import NexusProactiveWhen, OpenAIProvider


def on_ai_response(response: str):
    print(f"🤖 AI: {response}")


def on_decision_made(should_respond: bool, reasoning: str):
    decision = "✅ RESPOND" if should_respond else "❌ WAIT"
    print(f"🧠 {decision}: {reasoning}")


def main():
    provider = OpenAIProvider(
        model="gpt-5-nano",
    )
    
    # AI-based decision engine is used by default
    agent = NexusProactiveWhen(
        provider=provider,
        system_prompt="You are a helpful AI assistant.",
        decision_config={
            'min_response_interval': 30,
            'max_response_interval': 300,
        }
    )
    
    agent.add_callback(on_ai_response)
    agent.add_decision_callback(on_decision_made)
    agent.start()
    
    print("=== AI-Based Decision Engine ===")
    print("AI analyzes context to decide when to respond.")
    print("Type 'quit' to exit.\n")
    
    while True:
        message = input("You: ").strip()
        if message.lower() == 'quit': break
        agent.send_message(message)
        time.sleep(1)

    agent.stop()


if __name__ == "__main__":
    main()