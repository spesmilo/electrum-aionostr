# Release History / Changelog

* **Release v0.1.0 (2025-12-11)**

    - Event class: minor API changes, most importantly Event is now immutable (#21)
    - add some mitigations against misbehaving/malicious relays and related bug fixes
      - fix some memory exhaustion attacks (#15, cfe4b79e)
      - don't let one relay miss us events from other relays (#16, #20, dbf0b7f1)
      - Relay._receive_messages: sleep a bit between each message (38b6f2d6)
    - (fix) manager: more robust clean-up on timeouts (#19)
    - dependencies: instead of requiring `cryptography`, allow choice
      between `pycryptodomex` and `cryptography` (#18)


* **Release v0.0.11 (2025-06-10)**

    - fix tests for Click>=8.2
    - add expiration helper methods to Event class
    - Manager.get_events: filter out events with future timestamps


* **Release v0.0.10 (2025-05-08)**

    - bump max supported `aiorpcx` to `<0.26`
    - fix proxy: pass connector_owner to ClientSession to prevent connector being closed
    - fix race condition causing subscription return duplicate events
    - manager: use actual passed connect timeout as timeout for connections


* **Release v0.0.9 (2025-03-20)**

    - Declare 'cryptography' dependency in optional extra `[crypto]`
        - For now, it is still always required. This change simplifies dependency management downstream for Electrum.


* **Release v0.0.8 (2025-03-19)**

    - Use correct public key type in `verify()` method
    - Always verify signatures of queried events (**Previous versions don't automatically verify signatures!**)
    - Add tests for signature verification
    - Switch from `websockets` to `aiohttp` library for websocket connections
    - Add support for proxy connections
    - Bump min required Python version to 3.10
    - Add method to dynamically change relay list on existing RelayManager
    - Use platform independent `os.urandom` instead of `getrandom` for tests
