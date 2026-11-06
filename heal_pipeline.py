import sys
from HEAL.core.orchestrator import HEALOrchestrator

def run_heal_pipeline():
    print("--- HEAL: Healthcare Execution-guided Conversational Multi-Agent Framework ---")
    print("Multi-Agent Text-to-SQL System (A, N, J, T Reasoning)")
    print("Type 'exit' or 'quit' to stop, 'reset' to clear conversation history.\n")
    
    orchestrator = HEALOrchestrator()
    
    while True:
        try:
            query = input("Clinician Query: ").strip()
            
            if not query:
                continue
            if query.lower() in ['exit', 'quit']:
                break
            if query.lower() == 'reset':
                orchestrator.reset()
                print("Conversation history reset.\n")
                continue
            
            print(f"Agent Pipeline Processing (LangGraph): '{query}'...")
            result_state = orchestrator.process_query(query)
            
            if result_state['error']:
                print(f"Execution Error: {result_state['error']}\n")
            else:
                print(f"[SQL Generated]: {result_state['sql']}")
                print(f"[Records Found]: {len(result_state['results']) if result_state['results'] else 0}")
                
                print(f"\n[Clinical Intent Plan (CIP)]:\n{result_state.get('clinical_plan', 'No plan generated.')}")
                
                print(f"\n[Cognitive Reasoning Trace]:")
                for trace in result_state.get('reasoning_trace', []):
                    print(f"  - {trace}")

                print(f"\n[HEAL Response]: {result_state['response']}")
                
                if result_state['results']:
                    print("\n[Preview]:")
                    for i, row in enumerate(result_state['results'][:3]):
                        print(f"  - {row}")
                print("\n" + "="*60 + "\n")
                
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"System Exception: {e}")

if __name__ == "__main__":
    run_heal_pipeline()
