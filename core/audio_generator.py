import asyncio
import edge_tts
import os
import json
import logging

logger = logging.getLogger(__name__)

class AudioGenerator:
    def __init__(self, voice="en-US-ChristopherNeural", rate="+0%", pitch="+0Hz", volume="+0%"):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        
    async def _generate_audio_async(self, text: str, output_path: str):
        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate, pitch=self.pitch, volume=self.volume)
        await communicate.save(output_path)
        
    def generate_audio(self, text: str, output_path: str):
        """Generates an MP3 from text using edge-tts."""
        # Use a new event loop to avoid 'already running' crash
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
            
        if loop and loop.is_running():
            # We're inside an existing event loop — run in a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self._generate_audio_async(text, output_path))
                future.result()
        else:
            asyncio.run(self._generate_audio_async(text, output_path))
        return output_path
        
    def get_audio_duration_ms(self, file_path: str) -> int:
        """
        Gets the duration of an audio file in milliseconds using mutagen.
        """
        try:
            from mutagen.mp3 import MP3
            audio = MP3(file_path)
            # Add 250ms padding so CapCut doesn't cut off the very end of the word
            return int(audio.info.length * 1000) + 250
        except Exception as e:
            logger.warning(f"Failed to get exact audio duration using mutagen: {e}")
            return 3000

    def generate_scene_audio(self, ocr_text_list, output_path: str) -> int:
        """
        Generates TTS for a single scene and returns duration in microseconds (for CapCut).
        Returns 3000000 (3 seconds) if no text.
        """
        if not ocr_text_list:
            return 3000000
            
        if isinstance(ocr_text_list, list):
            text = " ".join([t.strip() for t in ocr_text_list if t.strip()])
        else:
            text = str(ocr_text_list).strip()
            
        if len(text) < 2:
            return 3000000
            
        if not text.endswith(('.', '!', '?')):
            text += "."
            
        try:
            self.generate_audio(text, output_path)
            duration_ms = self.get_audio_duration_ms(output_path)
            return duration_ms * 1000 # Convert to microseconds for CapCut
        except Exception as e:
            logger.error(f"Scene TTS Error: {e}")
            return 3000000

    def process_script_to_audio(self, script_text: str, output_dir: str, callback=None):
        """
        Takes the full generated script, splits it into logical scenes/paragraphs,
        generates an MP3 for each, and returns a timeline mapping for CapCut.
        """
        os.makedirs(output_dir, exist_ok=True)
        
        paragraphs = [p.strip() for p in script_text.split('\n\n') if p.strip()]
        timeline_data = []
        
        for i, para in enumerate(paragraphs):
            audio_filename = f"voiceover_{i:04d}.mp3"
            audio_path = os.path.join(output_dir, audio_filename)
            
            msg = f"Generating audio {i+1}/{len(paragraphs)}..."
            if callback:
                callback(msg)
            else:
                logger.info(msg)
                
            try:
                self.generate_audio(para, audio_path)
                duration_ms = self.get_audio_duration_ms(audio_path)
                
                timeline_data.append({
                    "scene_index": i,
                    "text": para,
                    "audio_filename": audio_filename,
                    "duration_ms": duration_ms
                })
            except Exception as e:
                err_msg = f"Failed to generate audio {i+1}: {e}"
                if callback:
                    callback(f"[ERROR] {err_msg}")
                else:
                    logger.error(err_msg)
                    
                # Silence Injection Fallback
                try:
                    from pydub import AudioSegment
                    # Estimate duration: ~150 words per minute -> 2.5 words per second
                    word_count = len(para.split())
                    estimated_duration_ms = int((word_count / 2.5) * 1000)
                    if estimated_duration_ms < 1000:
                        estimated_duration_ms = 1000
                        
                    silent_segment = AudioSegment.silent(duration=estimated_duration_ms)
                    silent_segment.export(audio_path, format="mp3")
                    
                    timeline_data.append({
                        "scene_index": i,
                        "text": para,
                        "audio_filename": audio_filename,
                        "duration_ms": estimated_duration_ms
                    })
                    
                    if callback:
                        callback(f"[FALLBACK] Injected {estimated_duration_ms/1000:.1f}s of silence to prevent desync.")
                except Exception as fallback_e:
                    logger.error(f"Fallback silence generation failed: {fallback_e}")
            
        meta_path = os.path.join(output_dir, "audio_timeline.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(timeline_data, f, indent=2)
            
        if callback:
            callback("Voiceover Generation Complete!")
            
        return timeline_data

    def generate_combined_audio(self, script_text: str, output_dir: str, callback=None):
        """
        Generates per-paragraph MP3s and concatenates them into ONE long MP3.
        Returns (combined_audio_path, total_duration_ms, timeline_data).
        """
        # Step 1: Generate individual paragraph audio files
        timeline_data = self.process_script_to_audio(script_text, output_dir, callback)
        
        if not timeline_data:
            return None, 0, []
        
        # Step 2: Concatenate into one long MP3
        combined_path = os.path.join(output_dir, "combined_voiceover.mp3")
        
        try:
            from pydub import AudioSegment
            import pydub
            
            # Point to local ffmpeg if it exists by adding it to PATH
            ffmpeg_dir = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "bin", "ffmpeg"))
            if os.path.exists(ffmpeg_dir):
                os.environ["PATH"] += os.pathsep + ffmpeg_dir
                pydub.AudioSegment.converter = os.path.join(ffmpeg_dir, "ffmpeg.exe")
                
            combined = AudioSegment.empty()
            for entry in timeline_data:
                audio_path = os.path.join(output_dir, entry["audio_filename"])
                if os.path.exists(audio_path):
                    segment = AudioSegment.from_mp3(audio_path)
                    combined += segment
                    # Add a small pause between paragraphs (300ms)
                    combined += AudioSegment.silent(duration=300)
                    
            combined.export(combined_path, format="mp3")
            total_duration_ms = len(combined)
            
            if callback:
                callback(f"Combined audio saved: {total_duration_ms / 1000:.1f}s total")
                
        except ImportError:
            # Fallback: binary concatenation (less reliable but works)
            logger.warning("pydub not available. Using binary concatenation fallback.")
            with open(combined_path, 'wb') as outfile:
                total_duration_ms = 0
                for entry in timeline_data:
                    audio_path = os.path.join(output_dir, entry["audio_filename"])
                    if os.path.exists(audio_path):
                        with open(audio_path, 'rb') as infile:
                            outfile.write(infile.read())
                        total_duration_ms += entry["duration_ms"]
                        
            if callback:
                callback(f"Combined audio saved (fallback mode): {total_duration_ms / 1000:.1f}s total")
        except Exception as e:
            logger.error(f"Failed to combine audio: {e}")
            if callback:
                callback(f"[ERROR] Failed to combine audio: {e}")
            return None, 0, timeline_data
        
        return combined_path, total_duration_ms, timeline_data
