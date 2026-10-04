"""Is POST /external/v1/submissions (API doc 2.8) deployed yet?

Safe by construction: `submissionType` is deliberately invalid, so their validator rejects the
payload before anything could be inserted into the review queue. What we are reading is WHICH
layer answered.

  400 INVALID_SUBMISSION_TYPE  -> the route exists and our key has the LEADS scope
  403 with a JSON errorCode    -> the route exists, the key is not scoped for it
  403 with an empty body       -> the key was not accepted at all
  404                          -> the route is not deployed on this host
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests                                   # noqa: E402

from app import create_app                        # noqa: E402
from app.services import preventia                # noqa: E402

app = create_app()
with app.app_context():
    base, key = preventia.base_url(), preventia.api_key()
    print('configured:', bool(base and key), '| base:', base)

    def show(label, r):
        try:
            body = json.dumps(r.json())[:200]
        except Exception:
            body = repr((r.text or '')[:140]) or '(empty body)'
        print('%-46s %s  %s' % (label, r.status_code, body))

    s = requests.Session()
    s.headers['X-API-Key'] = key

    # the control: the read half we already rely on
    show('GET  /external/v1/roles', s.get(base + '/external/v1/roles', timeout=20))

    probe = {'submissionType': 'NOT_A_REAL_TYPE', 'source': 'probe',
             'fullName': 'scope probe', 'phone': '0000000000'}
    show('POST /external/v1/submissions',
         s.post(base + '/external/v1/submissions', json=probe, timeout=20))
