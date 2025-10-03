import requests
import time
import math
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from flask import Flask, Response, abort, stream_with_context, jsonify
from queue import Queue
from threading import Thread, Event

# ==============================================================================
# --- ADVANCED & ROBUST DASH MANIFEST PARSER ---
# ==============================================================================

def _get_attrib(element, attrib_name, default=None):
    return element.attrib.get(attrib_name, default)

def _parse_duration(duration_str: str) -> float:
    if not duration_str or not duration_str.startswith("PT"): return 0.0
    duration, pattern = 0.0, re.compile(r"(\d+(?:\.\d+)?)([HMS])")
    parts = pattern.findall(duration_str[2:])
    for value, unit in parts:
        v = float(value)
        if unit == 'H': duration += v * 3600
        elif unit == 'M': duration += v * 60
        elif unit == 'S': duration += v
    return duration

def _format_template(template_str, number=None, time=None):
    def replace_func(match):
        name, fmt = match.group(1), match.group(2)
        value = number if name == 'Number' else time
        if value is None: return ""
        if fmt: return f"{value:{fmt.lstrip('%')}}"
        return str(value)
    return re.sub(r'\$(Number|Time)(%[\da-zA-Z]+)?\$', replace_func, template_str)

def parse_mpd(mpd_url: str):
    try:
        print(f"[Parser] Fetching MPD from: {mpd_url}")
        response = requests.get(mpd_url, timeout=10)
        response.raise_for_status()
        base_url = response.url.rsplit('/', 1)[0] + '/'
        root = ET.fromstring(response.text)
        ns = {'mpd': 'urn:mpeg:dash:schema:mpd:2011'}
        
        mpd_type = _get_attrib(root, 'type', 'static')
        print(f"[Parser] MPD Type: {mpd_type}")
        
        tracks = {}
        period = root.find('mpd:Period', ns)
        if period is None: 
            print("[Parser] ERROR: No Period found in MPD")
            return None, None

        for adaptation_set in period.findall('mpd:AdaptationSet', ns):
            content_type = _get_attrib(adaptation_set, 'contentType', 'unknown')
            
            # Try to get segment template from AdaptationSet or Representation
            segment_template = adaptation_set.find('mpd:SegmentTemplate', ns)
            
            for rep in adaptation_set.findall('mpd:Representation', ns):
                rep_id = _get_attrib(rep, 'id')
                if not rep_id:
                    print("[Parser] WARNING: Representation without ID, skipping")
                    continue
                
                # Check if Representation has its own SegmentTemplate
                rep_segment_template = rep.find('mpd:SegmentTemplate', ns)
                current_template = rep_segment_template if rep_segment_template is not None else segment_template
                
                if current_template is None:
                    print(f"[Parser] WARNING: No SegmentTemplate for '{rep_id}', skipping")
                    continue
                
                key = f"{content_type}_{rep_id}"
                urls = []
                
                # Initialization segment
                init_template = _get_attrib(current_template, 'initialization')
                if init_template:
                    init_url = _format_template(init_template).replace('$RepresentationID$', rep_id)
                    urls.append(urljoin(base_url, init_url))
                    print(f"[Parser] Added init segment for '{rep_id}'")

                # Media template check
                media_template = _get_attrib(current_template, 'media')
                if not media_template:
                    print(f"[Parser] WARNING: Representation '{rep_id}' has no media template. Skipping.")
                    continue
                
                start_number = int(_get_attrib(current_template, 'startNumber', 1))
                timeline = current_template.find('mpd:SegmentTimeline', ns)
                
                if timeline is not None:
                    # SegmentTimeline logic
                    current_time = 0
                    current_number = start_number
                    for s_tag in timeline.findall('mpd:S', ns):
                        d_str = _get_attrib(s_tag, 'd')
                        if d_str is None:
                            print(f"[Parser] WARNING: Skipping <S> tag for '{rep_id}' due to missing 'd' attribute.")
                            continue
                        d = int(d_str)
                        t_str = _get_attrib(s_tag, 't')
                        current_time = int(t_str) if t_str is not None else current_time
                        r = int(_get_attrib(s_tag, 'r', 0))
                        for _ in range(r + 1):
                            media_url = _format_template(media_template, number=current_number, time=current_time).replace('$RepresentationID$', rep_id)
                            urls.append(urljoin(base_url, media_url))
                            current_time += d
                            current_number += 1
                    print(f"[Parser] Added {len(urls)-1} timeline segments for '{rep_id}'")
                else:
                    # VOD fallback logic
                    media_duration = _parse_duration(_get_attrib(root, 'mediaPresentationDuration'))
                    timescale = int(_get_attrib(current_template, 'timescale', 1))
                    seg_duration_units = int(_get_attrib(current_template, 'duration', 0))
                    
                    if seg_duration_units > 0 and timescale > 0 and media_duration > 0:
                        segment_len_secs = seg_duration_units / timescale
                        segment_count = math.ceil(media_duration / segment_len_secs)
                        print(f"[Parser] Calculated {segment_count} segments for '{rep_id}' (duration={media_duration}s)")
                        for i in range(segment_count):
                            number = start_number + i
                            media_url = _format_template(media_template, number=number).replace('$RepresentationID$', rep_id)
                            urls.append(urljoin(base_url, media_url))
                    else:
                        print(f"[Parser] WARNING: Cannot calculate segments for '{rep_id}' - missing duration info")
                        continue
                
                if len(urls) == 0:
                    print(f"[Parser] WARNING: No URLs generated for '{rep_id}', skipping")
                    continue
                
                tracks[key] = {
                    'key': key, 'id': rep_id, 'type': content_type,
                    'bandwidth': int(_get_attrib(rep, 'bandwidth', 0)),
                    'urls': urls
                }
        
        print(f"[Parser] Successfully parsed {len(tracks)} tracks")
        return tracks, mpd_type
        
    except requests.RequestException as e:
        print(f"[Parser] Network error: {e}")
        return None, None
    except ET.ParseError as e:
        print(f"[Parser] XML parsing error: {e}")
        return None, None
    except Exception as e:
        print(f"[Parser] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# ==============================================================================
# --- FLASK STREAMING APPLICATION ---
# ==============================================================================

def reconstruct_url_from_path(path_segment):
    if path_segment.startswith('http:/') and not path_segment.startswith('http://'): 
        return path_segment.replace('http:/', 'http://', 1)
    if path_segment.startswith('https:/') and not path_segment.startswith('https://'): 
        return path_segment.replace('https:/', 'https://', 1)
    return path_segment

def segment_fetcher(q: Queue, session: requests.Session, track: dict, mpd_type: str, mpd_url: str, stop_event: Event):
    try:
        if mpd_type == 'static':
            all_urls = track['urls']
            loop_count = 0
            while not stop_event.is_set():
                loop_count += 1
                print(f"[Fetcher] Starting VOD loop #{loop_count}")
                for idx, segment_url in enumerate(all_urls):
                    if stop_event.is_set(): 
                        break
                    try:
                        resp = session.get(segment_url, timeout=10)
                        resp.raise_for_status()
                        q.put(resp.content)
                        print(f"[Fetcher] Queued media segment {idx+1}/{len(all_urls)} ({len(resp.content)} bytes)")
                    except requests.RequestException as e:
                        print(f"[Fetcher] Error fetching segment: {e}")
                if stop_event.is_set(): 
                    break
        else:  # 'dynamic' (Live) Logic
            sent_segments = set()
            track_key = track['key']
            while not stop_event.is_set():
                live_tracks, _ = parse_mpd(mpd_url)
                if not live_tracks:
                    print("[Fetcher] Could not re-fetch live manifest. Waiting...")
                    time.sleep(2)
                    continue
                if track_key not in live_tracks or not live_tracks[track_key]['urls']:
                    print(f"[Fetcher] Track key '{track_key}' disappeared or has no segments. Stopping.")
                    break
                all_current_urls = live_tracks[track_key]['urls']
                found_new = False
                for segment_url in all_current_urls:
                    if stop_event.is_set(): 
                        break
                    if segment_url not in sent_segments:
                        found_new = True
                        try:
                            resp = session.get(segment_url, timeout=10)
                            resp.raise_for_status()
                            q.put(resp.content)
                            sent_segments.add(segment_url)
                            print(f"[Fetcher] Queued NEW live segment: {segment_url.split('/')[-1]}")
                        except requests.RequestException as e:
                            print(f"[Fetcher] Error fetching live segment: {e}")
                if not found_new:
                    print(f"[Fetcher] No new segments. Waiting 2.00s...")
                    time.sleep(2.0)
    except Exception as e:
        print(f"[Fetcher] FATAL Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        q.put(None)
        print("[Fetcher] Fetcher thread finished.")

app = Flask(__name__)

def check_drm_protection(mpd_url: str):
    """Check if MPD contains DRM-protected content"""
    try:
        response = requests.get(mpd_url, timeout=10)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        ns = {'mpd': 'urn:mpeg:dash:schema:mpd:2011'}
        
        # Check for ContentProtection elements
        period = root.find('mpd:Period', ns)
        if period:
            for adaptation_set in period.findall('mpd:AdaptationSet', ns):
                protection = adaptation_set.find('mpd:ContentProtection', ns)
                if protection is not None:
                    scheme = protection.get('schemeIdUri', '')
                    if 'EDEF8BA9' in scheme.upper():  # Widevine
                        return True, "Widevine"
                    elif '9A04F079' in scheme.upper():  # PlayReady
                        return True, "PlayReady"
                    elif 'cenc' in scheme.lower():
                        return True, "CENC (Generic)"
        return False, None
    except:
        return False, None

@app.route('/debug/<path:mpd_url_path>')
def debug(mpd_url_path):
    """Debug endpoint to see what tracks are available"""
    mpd_url = reconstruct_url_from_path(mpd_url_path)
    
    # Check for DRM
    is_drm, drm_type = check_drm_protection(mpd_url)
    
    tracks, mpd_type = parse_mpd(mpd_url)
    
    if not tracks:
        return jsonify({"error": "Could not parse MPD", "url": mpd_url}), 500
    
    result = {
        "mpd_url": mpd_url,
        "mpd_type": mpd_type,
        "drm_protected": is_drm,
        "drm_type": drm_type if is_drm else None,
        "warning": "Content is DRM-protected and cannot be played without decryption" if is_drm else None,
        "tracks": {k: {
            "id": v['id'],
            "type": v['type'],
            "bandwidth": v['bandwidth'],
            "segment_count": len(v['urls'])
        } for k, v in tracks.items()}
    }
    return jsonify(result)

@app.route('/stream/<stream_type>/<path:mpd_url_path>')
def stream(stream_type, mpd_url_path):
    if stream_type not in ['video', 'audio']:
        abort(404, "Stream type must be 'video' or 'audio'")
    
    mpd_url = reconstruct_url_from_path(mpd_url_path)
    print(f"\n[Stream] Parsing MPD: {mpd_url}")
    
    # Check for DRM protection and warn user
    is_drm, drm_type = check_drm_protection(mpd_url)
    if is_drm:
        print(f"[Stream] WARNING: Content is DRM-protected ({drm_type}). Segments will be encrypted!")

    initial_tracks, mpd_type = parse_mpd(mpd_url)
    
    if not initial_tracks:
        abort(500, f"Error: Could not parse MPD from {mpd_url}")

    print(f"[Stream] MPD type: {mpd_type}")
    print(f"[Stream] Available tracks: {list(initial_tracks.keys())}")
    
    target_tracks = {k: v for k, v in initial_tracks.items() if stream_type in k.lower()}
    
    if not target_tracks:
        abort(404, f"No '{stream_type}' tracks found. Available tracks: {list(initial_tracks.keys())}")
    
    # Filter tracks with actual URLs
    valid_tracks = {k: v for k, v in target_tracks.items() if v['urls'] and len(v['urls']) > 0}
    
    if not valid_tracks:
        abort(500, f"No valid '{stream_type}' tracks with segments found")
    
    best_track = max(valid_tracks.values(), key=lambda t: t['bandwidth'])
    print(f"[Stream] Selected track: {best_track['id']} with {len(best_track['urls'])} initial segments")

    def generate_stream():
        segment_queue = Queue(maxsize=10)
        stop_event = Event()
        session = requests.Session()
        fetcher_thread = Thread(target=segment_fetcher, args=(segment_queue, session, best_track, mpd_type, mpd_url, stop_event))
        fetcher_thread.daemon = True
        fetcher_thread.start()
        
        try:
            while True:
                segment_data = segment_queue.get()
                if segment_data is None:
                    break
                yield segment_data
        except GeneratorExit:
            print("[Streamer] Client disconnected.")
        finally:
            print("[Streamer] Cleaning up...")
            stop_event.set()
            session.close()
            fetcher_thread.join(timeout=5)
            print("[Streamer] Cleanup complete.")

    mimetype = 'video/mp4' if stream_type == 'video' else 'audio/mp4'
    return Response(stream_with_context(generate_stream()), mimetype=mimetype)

if __name__ == '__main__':
    print("--- DASH Streaming Proxy (Enhanced Error Handling) ---")
    print("\nTo run, install dependencies: pip install Flask requests waitress")
    print("\nExample VOD:")
    print("  http://127.0.0.1:8080/stream/video/https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd")
    print("\nExample LIVE (with SegmentTimeline):")
    print("  http://127.0.0.1:8080/stream/video/https://dash.akamaized.net/dash264/TestCases/1c/qualcomm/2/MultiRate.mpd")
    print("\nDebug endpoint to see available tracks:")
    print("  http://127.0.0.1:8080/debug/https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd")
    
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=8080)
    except ImportError:
        app.run(host='0.0.0.0', port=8080, threaded=True)
