Got it 👍 — here’s the **entire document wrapped fully in Markdown**, ready to drop into a GitHub `README.md` file
# DASHProxy

A lightweight Flask-based proxy server that converts MPEG-DASH (Dynamic Adaptive Streaming over HTTP) manifests into streamable HTTP content. Perfect for accessing DASH video/audio streams in environments or players that don't natively support the DASH protocol.

---

## ✨ Features

- ✅ **VOD & Live Stream Support** – Handles both static (VOD) and dynamic (live) DASH streams  
- ✅ **Advanced MPD Parsing** – Supports `SegmentTimeline`, `SegmentTemplate`, and duration-based segmentation  
- ✅ **Auto Track Selection** – Automatically selects the highest quality video/audio track  
- ✅ **DRM Detection** – Identifies DRM-protected content (Widevine, PlayReady, CENC)  
- ✅ **Debug Endpoint** – Inspect available tracks and stream information  
- ✅ **Loop Playback** – VOD streams automatically loop for continuous playback  
- ✅ **Robust Error Handling** – Graceful handling of network errors and malformed manifests  

---

## 🚀 Installation

### Requirements
- Python 3.7+
- Flask
- Requests
- Waitress (recommended for production)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/dashproxy.git
cd dashproxy

# Install dependencies
pip install Flask requests waitress

# Run the server
python dashproxy.py
````

The server will start at:
`http://0.0.0.0:8080`

---

## 🎬 Usage

### Stream Endpoint

Convert a DASH manifest to a streamable HTTP endpoint:

```
http://127.0.0.1:8080/stream/{type}/{mpd_url}
```

* `{type}`: Either `video` or `audio`
* `{mpd_url}`: The full URL to the DASH manifest (`.mpd` file)

**Examples:**

```bash
# Stream video from a VOD DASH manifest
http://127.0.0.1:8080/stream/video/https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd

# Stream audio only
http://127.0.0.1:8080/stream/audio/https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd

# Stream live content
http://127.0.0.1:8080/stream/video/https://dash.akamaized.net/dash264/TestCases/1c/qualcomm/2/MultiRate.mpd
```

---

### Debug Endpoint

Inspect available tracks and stream information:

```
http://127.0.0.1:8080/debug/{mpd_url}
```

**Example:**

```bash
http://127.0.0.1:8080/debug/https://dash.akamaized.net/akamai/bbb_30fps/bbb_30fps.mpd
```

Returns JSON with:

* MPD type (static/dynamic)
* DRM protection status
* Available tracks with bandwidth and segment counts
* Track IDs and types

---

## ⚙️ How It Works

1. **Parse MPD** → Fetch and parse the DASH manifest XML
2. **Extract Segments** → Identify all media segment URLs using `SegmentTemplate` or `SegmentTimeline`
3. **Select Track** → Choose the highest-bandwidth track for the requested type
4. **Stream Segments** → Fetch segments sequentially and stream them to the client
5. **Loop/Update** → VOD loops content; live refreshes the manifest for new segments

---

## 🔐 DRM & Decryption

⚠️ **DRM-Protected Content**: This proxy itself **cannot decrypt** DRM-protected streams.
However, it **can be used with FFmpeg** to decrypt Widevine-protected content if you already have the decryption keys.

### Decrypting with FFmpeg

If you have valid decryption keys, use FFmpeg:

```bash
ffmpeg -decryption_key "YOUR_KEY_HERE" \
       -i "http://127.0.0.1:8080/stream/audio/https://example.com/manifest.mpd" \
       -decryption_key "YOUR_KEY_HERE" \
       -i "http://127.0.0.1:8080/stream/video/https://example.com/manifest.mpd" \
       -c copy output.mp4
```

**Example with real parameters:**

```bash
ffmpeg -decryption_key "fd9a7a53157516493c1332938b22b6d8" \
       -i "http://127.0.0.1:8080/stream/audio/https://ac-003.live.p7s1video.net/e85065ab/t_009/nickelodeon-de/cenc-default.mpd" \
       -decryption_key "fd9a7a53157516493c1332938b22b6d8" \
       -i "http://127.0.0.1:8080/stream/video/https://ac-003.live.p7s1video.net/e85065ab/t_009/nickelodeon-de/cenc-default.mpd" \
       -c copy output.mp4
```

Workflow:

1. DASHProxy converts DASH manifests to HTTP endpoints
2. FFmpeg fetches encrypted segments via DASHProxy
3. FFmpeg decrypts them using provided keys
4. FFmpeg muxes audio + video into a single file

> **Note:** You must obtain decryption keys legally. This tool does **not** provide or extract keys.

---

## ⚠️ Limitations

* **Performance**: Not optimized for high concurrency; use a production WSGI server and caching
* **No Adaptive Bitrate**: Always selects the highest quality track; no ABR switching

---

## 🛠 Use Cases

* Playing DASH streams in players that only support HTTP progressive download
* Testing/debugging DASH manifests
* Converting DASH streams for legacy systems
* Educational/DASH protocol analysis

---

## ⚡ Configuration

Edit the `if __name__ == '__main__'` section to change:

* **Host**: Default `0.0.0.0` (all interfaces)
* **Port**: Default `8080`
* **Server**: Uses Waitress if available; falls back to Flask dev server

---

## 🤝 Contributing

Contributions are welcome! Please submit a Pull Request.

---

## 📜 License

MIT License – free to use for any purpose.

---

## ⚖️ Disclaimer

This tool is for **educational and testing purposes only**.
Ensure you have the rights to access and redistribute any content you stream. Respect copyright.

---

## 🙏 Acknowledgments

* Built with Flask and the MPEG-DASH specification
* Tested with Akamai’s public DASH test streams

---

💡 **Need help?** Open an issue on GitHub or check the `/debug` endpoint for details.

Want me to also generate a **table of contents** with automatic GitHub anchors at the top?
```
