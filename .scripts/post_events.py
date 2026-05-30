import json
import httpx

def main():
    p='tests/fixtures/sample_events.jsonl'
    with open(p) as f:
        events=[json.loads(line) for line in f if line.strip()]
    print('Loaded',len(events),'events')
    url='http://127.0.0.1:8000/events/ingest'
    resp = httpx.post(url, json={'events': events})
    print('POST',resp.status_code, resp.text)
    murl='http://127.0.0.1:8000/stores/STORE_BLR_002/metrics'
    resp2 = httpx.get(murl)
    print('GET metrics', resp2.status_code)
    print(resp2.text)

if __name__ == '__main__':
    main()
