"""Module to test Context functionality"""

import threading
import time

from protean.context import Context
from protean.context import context


def test_with_thread_interloop():
    """Test if values are retained correctly"""
    # Collect results from thread runs
    results = []

    def request_url_value(request_url, sleep=0):
        """Assert on Request URL"""
        with Context():
            # Sleep for some determinate time to allow other threads to move forward
            time.sleep(sleep)
            results.append(context.request_url == request_url)

    # Interloop between threads
    t1 = threading.Thread(target=request_url_value, args=('default.talentxapp.com', 0.5,))
    t1.start()
    t2 = threading.Thread(target=request_url_value, args=('other.talentxapp.com',))
    t2.start()
    t1.join()

    # If context was not correct, a result could have been false
    assert any(result is False for result in results) is False
