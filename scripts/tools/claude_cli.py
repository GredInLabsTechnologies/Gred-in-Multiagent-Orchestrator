import os
import sys
import anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live

# Load environment variables from .env if present
load_dotenv()

# Initialize Rich console
console = Console()

def get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        console.print("[bold red]Error:[/bold red] ANTHROPIC_API_KEY not found in environment or .env file.")
        console.print("Please set it with: [bold]export ANTHROPIC_API_KEY='your-key-here'[/bold]")
        sys.exit(1)
    return anthropic.Anthropic(api_key=api_key)

def chat():
    client = get_client()
    messages = []
    model = "claude-3-5-sonnet-20240620"
    
    console.print(Panel.fit(
        "[bold magenta]Claude CLI Chat[/bold magenta]\n"
        "Type [bold cyan]/exit[/bold cyan] or [bold cyan]/quit[/bold cyan] to end the session.\n"
        "Type [bold cyan]/clear[/bold cyan] to reset history.",
        title="Welcome",
        border_style="magenta"
    ))

    while True:
        try:
            user_input = console.input("[bold green]You:[/bold green] ").strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["/exit", "/quit"]:
                console.print("[yellow]Goodbye![/yellow]")
                break
                
            if user_input.lower() == "/clear":
                messages = []
                console.print("[yellow]Chat history cleared.[/yellow]")
                continue

            messages.append({"role": "user", "content": user_input})

            with console.status("[bold blue]Claude is thinking...", spinner="dots"):
                response_text = ""
                with client.messages.stream(
                    model=model,
                    max_tokens=4096,
                    messages=messages,
                ) as stream:
                    console.print("[bold magenta]Claude:[/bold magenta] ", end="")
                    for text in stream.text_stream:
                        print(text, end="", flush=True)
                        response_text += text
                    print() # New line after stream

            messages.append({"role": "assistant", "content": response_text})
            
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Type /exit to quit.[/yellow]")
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {str(e)}")

if __name__ == "__main__":
    chat()
