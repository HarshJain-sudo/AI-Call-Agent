import plivo
from quart import Quart, websocket, Response, request
import asyncio
import websockets
import json
import base64
from dotenv import load_dotenv
import os
import requests


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'), override=True)

LIVE_API_KEY = os.getenv('GOOGLE_API_KEY')

PORT = 5000

app = Quart(__name__)
stream_id = ""
start_streaming = False

@app.route("/webhook", methods=["GET", "POST"])
def home():
    xml_data = f'''<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Stream streamTimeout="86400" keepCallAlive="true" bidirectional="true" contentType="audio/x-l16;rate=16000" audioTrack="inbound" >
            ws://{request.host}/media-stream
        </Stream>
    </Response>
    '''
    return Response(xml_data, mimetype='application/xml')

@app.websocket('/media-stream')
async def handle_message():
    print('client connected')
    plivo_ws = websocket 
    url = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={LIVE_API_KEY}"

    try: 
        async with websockets.connect(url) as goog_live_ws:
            print('connected to the Google Live WSS')

            await send_Session_update(goog_live_ws)
            
            receive_task = asyncio.create_task(receive_from_plivo(plivo_ws, goog_live_ws))
            
            async for message in goog_live_ws:
                await receive_from_goog_live(message, plivo_ws)
            
            await receive_task
    
    except asyncio.CancelledError:
        print('client disconnected')
    except websockets.ConnectionClosed:
        print("Connection closed by Google Live server")
    except Exception as e:
        print(f"Error during Google Live's websocket communication: {e}")
        
        
        
            
async def receive_from_plivo(plivo_ws, goog_live_ws):
    print('receiving from plivo')
    BUFFER_SIZE = 20 * 160
    inbuffer = bytearray(b"")
    try:
        while True:
            message = await plivo_ws.receive()
            data = json.loads(message)
            if data['event'] == 'media' and goog_live_ws.open and start_streaming:
                chunk = base64.b64decode(data['media']['payload'])
                inbuffer.extend(chunk)
               
            elif data['event'] == "start":
                print('Plivo Audio stream has started')
                stream_id = data['start']['streamId']
                print('stream id: ', stream_id)
            
            while len(inbuffer) >= BUFFER_SIZE:
                chunk = inbuffer[:BUFFER_SIZE]
                msg = {
                    "realtime_input": {
                        "media_chunks": [
                            {
                                "mime_type": "audio/pcm;rate=16000",
                                "data": base64.b64encode(chunk).decode(),
                            },
                        ]
                    },
                }
                await goog_live_ws.send(json.dumps(msg))
                inbuffer = inbuffer[BUFFER_SIZE:]

    except websockets.ConnectionClosed:
        print('Connection closed for the plivo audio streaming servers')
        if goog_live_ws.open:
            await goog_live_ws.close()
    except Exception as e:
        print(f"Error during Plivo's websocket communication: {e}")
        

async def receive_from_goog_live(message, plivo_ws):
    global start_streaming
    try:
        response = json.loads(message)
        if "setupComplete" in response:
            print('Google Live Setup complete')
            start_streaming = True
        
        if "serverContent" in response:
            if "interrupted" in response.get('serverContent', {}):
                print('Speech Interrupted')
                data = {
                    "event": "clearAudio",
                    "stream_id": stream_id
                }
                await plivo_ws.send(json.dumps(data))
            if "modelTurn" in response.get('serverContent', {}):
                parts = response.get('serverContent', {}).get('modelTurn', {}).get('parts')
                if parts[0].get('inlineData', {}).get('data'):
                    audioDelta = {
                        "event": 'playAudio',
                        "media": {
                            "contentType": 'audio/x-l16',
                            "sampleRate": 24000,
                            "payload": parts[0].get('inlineData', {}).get('data'),
                        }
                    }
                    await plivo_ws.send(json.dumps(audioDelta))
    except Exception as e:
        print(f"Error during Google Live's websocket communication: {e}")
    
    
async def send_Session_update(goog_live_ws):
    sessionSetupMessage = {
      "setup": {
          "model": "models/gemini-2.0-flash-live-001",
          "generation_config": {
            "response_modalities": "audio",
            "speech_config": {
              "voice_config": {
                "prebuilt_voice_config": {
                  "voice_name": "Fenrir" 
                },
              }
            }
          },
          "tools": { "google_search": {} }
        },
    }
    await goog_live_ws.send(json.dumps(sessionSetupMessage))
        


if __name__ == "__main__":
    print('running the server')
    client = plivo.RestClient(auth_id=os.getenv('PLIVO_AUTH_ID'), auth_token=os.getenv('PLIVO_AUTH_TOKEN'))
    call_made = client.calls.create(
        from_=os.getenv('PLIVO_FROM_NUMBER'),
        to_=os.getenv('PLIVO_TO_NUMBER'),
        answer_url=os.getenv('PLIVO_ANSWER_XML'),
        answer_method='GET',)
    app.run(port=PORT)
    