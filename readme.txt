To start Mosquitto (MQTT Broker)

```
cd "C:\Program Files\mosquitto"
mosquitto -v -c mosquitto.conf
```

If there is already a process running then kill it and start again

```
(To Find the process ID)
netstat -ano | findstr :1883

taskkill /PID <pid> /F
```

To setup ngrok for telegram webhook

```
ngrok http 5000
```
Then copy the forwarding https address for example:- https://4f87-2401-4900-889f-7c2f-a461-26bf-337d-ff78.ngrok-free.app

Then using curl command redirect it

```
curl -X POST "https://api.telegram.org/bot<TELEGRAM TOKEN>/setWebhook?url=<ngrok https address>/webhook"
```

To check for webhook information

```
curl https://api.telegram.org/bot<TELEGRAM TOKEN>/getWebhookInfo
```