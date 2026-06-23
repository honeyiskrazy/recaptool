import os
import sys
import json
from script_tool import ProviderManager

FINAL_MERGE_PROMPT = """
You are the Ultimate Narrator for a massive, multi-hour YouTube Manhwa recap video. 
You are receiving multiple sequential "Arc Scripts" that make up an entire story saga. 
Your singular job is to stitch them together into one flawless, monolithic masterpiece of narration.

CRITICAL DIRECTIVE: ZERO COMPRESSION ALLOWED
- You are absolutely forbidden from summarizing or condensing the story.
- If the combined input is 5,000 words, your output MUST be roughly 5,000 words.
- Do NOT flatten action sequences. Do NOT skip emotional beats.
- Every single event, fight, conversation, and reveal from the input MUST exist in your output.
- If you summarize to save time, you fail. Narrate everything with full, rich detail.

NARRATIVE SEWING RULES (THE "INVISIBLE SEAM"):
1. The Hook: Delete the individual openings of all arcs EXCEPT the first one. Make the very first sentence of the video an absolute drop-kick of tension. No slow setups.
2. The Bridges: When Arc 1 ends and Arc 2 begins, stitch them together seamlessly. Remove standalone ending/opening sentences that feel like episode breaks. The listener should never know they crossed from one arc to another.
3. The Climax & Drop: Keep the momentum rising. Only let the audience breathe when the characters breathe.
4. The Final Note: The ending of the LAST arc is the ending of the video. Make it hit like a sledgehammer. If it's a cliffhanger, cut it off sharply.

VOICE & TONE (THE "DARK CINEMATIC" STYLE):
- Use visceral, punchy verbs (e.g., shatters, tears, forces, bleeds).
- Avoid weak filler transitions ("Meanwhile", "After that", "We then see", "The story shifts to"). 
- Action scenes: Short, kinetic sentences. High impact.
- Lore/Drama: Longer, sweeping sentences with emotional weight.
- Maintain consistent character names and remove redundant re-explanations of world lore if it was already explained in an earlier arc.

THE GOLDEN DIALOGUE RULE:
- QUOTATION MARKS ARE PERMANENTLY BANNED. Not a single pair is allowed.
- Convert all dialogue into narrated action. 
- WRONG: "I will kill you," he screamed.
- RIGHT: He screams that he will tear him apart, his voice shattering the silence.

OUTPUT FORMAT:
Plain spoken narration text only. 
No markdown. No "Arc 1" headers. No titles. No meta-commentary. 
Just one continuous, brutally captivating script.
"""

CONNECTOR_PROMPT = """
You are writing a transition for a massive manhwa recap script that had to be split in two halves.
I will provide the END of Half 1 and the BEGINNING of Half 2.
Write a seamless transition paragraph that connects them, replacing the standalone ending of Half 1 and the standalone opening of Half 2.
Output ONLY the transition text. Do not include quotes, headers, or anything else.
"""

def merge_arcs_to_final(arc_script_paths, output_path, provider=None):
    if not arc_script_paths or not output_path:
        raise ValueError("Error: arc_script_paths and output_path are required for final merge.")

    user_text_blocks = []
    for arc_path in arc_script_paths:
        if not os.path.exists(arc_path):
            raise FileNotFoundError(f"Error: Arc script {arc_path} not found.")
        with open(arc_path, 'r', encoding='utf-8') as f:
            user_text_blocks.append(f.read().strip())
            
    full_text = "\n\n".join(user_text_blocks)
    
    print(f"Merging {len(arc_script_paths)} arcs into final script...")
    pm = ProviderManager(provider_call2=provider)
    
    try:
        custom_final_merge = FINAL_MERGE_PROMPT
        if os.path.exists("prompts.json"):
            try:
                with open("prompts.json", "r", encoding="utf-8") as pf:
                    pd = json.load(pf)
                    custom_final_merge = pd.get("FINAL_MERGE_PROMPT", FINAL_MERGE_PROMPT)
            except: pass
            
        merged_text, is_truncated = pm.generate_text(custom_final_merge, full_text)
    except Exception as e:
        raise RuntimeError(f"Error during final merge: {e}")
        
    if is_truncated:
        print("Warning: Output truncated due to token limits. Triggering 2-part fallback merge...")
        half_idx = len(user_text_blocks) // 2
        half_1_text = "\n\n".join(user_text_blocks[:half_idx])
        half_2_text = "\n\n".join(user_text_blocks[half_idx:])
        
        print("  Merging First Half...")
        h1_merged, _ = pm.generate_text(custom_final_merge, half_1_text)
        
        print("  Merging Second Half...")
        h2_merged, _ = pm.generate_text(custom_final_merge, half_2_text)
        
        # Get the last 300 words of H1 and first 300 words of H2 for context
        h1_words = h1_merged.split()
        h2_words = h2_merged.split()
        
        h1_end = " ".join(h1_words[-300:]) if len(h1_words) > 300 else h1_merged
        h2_start = " ".join(h2_words[:300]) if len(h2_words) > 300 else h2_merged
        
        transition_context = f"END OF HALF 1:\n{h1_end}\n\nBEGINNING OF HALF 2:\n{h2_start}"
        
        print("  Generating transition...")
        transition_text, _ = pm.generate_text(CONNECTOR_PROMPT, transition_context)
        
        # Now concatenate. We'll strip the last paragraph of H1 and first paragraph of H2 to make room for transition
        h1_paras = h1_merged.split('\n\n')
        h2_paras = h2_merged.split('\n\n')
        
        if len(h1_paras) > 1:
            h1_body = "\n\n".join(h1_paras[:-1])
        else:
            h1_body = h1_merged
            
        if len(h2_paras) > 1:
            h2_body = "\n\n".join(h2_paras[1:])
        else:
            h2_body = h2_merged
            
        merged_text = f"{h1_body}\n\n{transition_text.strip()}\n\n{h2_body}"
        print("  Fallback merge complete.")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(merged_text)
        
    print(f"Done. Final script saved to {output_path} ({len(merged_text.split())} words).")
    return output_path
