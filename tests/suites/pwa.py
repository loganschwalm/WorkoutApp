"""Installability and offline reloads: the manifest, the service worker, and what it caches."""

import json
import socket

# The service worker must see the real network. Fetch interception would sit in front of it.
INTERCEPT = False


def run(t):
    cdp, check = t.cdp, t.check

    def ev_async(expression):
        """Runtime.evaluate already awaits promises, so async probes read like sync ones."""
        return cdp.ev(expression)

    def cached(path):
        return ev_async(f'caches.match({json.dumps(path)}).then(r => !!r)')

    def controlled():
        cdp.goto('/index.html')
        # First load registers; the worker only controls the page from the next one.
        cdp.ev('navigator.serviceWorker.ready.then(() => true)')
        cdp.goto('/index.html')
        return cdp.wait('navigator.serviceWorker.controller !== null', timeout=15)

    # ------------------------------------------------------------------ S1 served correctly
    print('S1  the manifest, worker and icons are served')
    for path in ('/manifest.webmanifest', '/sw.js', '/pwa.js',
                 '/icons/icon-192.png', '/icons/icon-512.png',
                 '/icons/icon-maskable-512.png', '/icons/apple-touch-icon.png'):
        status, _ = t.raw('GET', path)
        check(f'{path} is served without signing in', status == 200, f'HTTP {status}')

    manifest, _ = t.api('GET', '/manifest.webmanifest')
    check('manifest names the app', manifest.get('name') == 'Workout Tracker', str(manifest.get('name')))
    check('manifest is installable (standalone + start_url + scope)',
          manifest.get('display') == 'standalone' and manifest.get('start_url') == '/index.html'
          and manifest.get('scope') == '/', str(manifest))
    sizes = {icon.get('sizes') for icon in manifest.get('icons', [])}
    check('manifest offers 192px and 512px icons', {'192x192', '512x512'} <= sizes, str(sizes))
    purposes = {icon.get('purpose') for icon in manifest.get('icons', [])}
    check('manifest offers a maskable icon', 'maskable' in purposes, str(purposes))

    cdp.goto('/index.html')
    mime = ev_async("fetch('/manifest.webmanifest').then(r => r.headers.get('content-type'))")
    check('manifest is served as JSON', mime and 'json' in mime, str(mime))

    # ------------------------------------------------------------------ S2 registration
    print('S2  the service worker registers and takes control')
    check('127.0.0.1 is a secure context, so a worker is allowed',
          cdp.ev('window.isSecureContext') is True)
    check('the worker controls the page after a reload', controlled() is True)
    scope = cdp.ev("navigator.serviceWorker.controller.scriptURL")
    check('it is our worker at the site root', scope.endswith('/sw.js'), str(scope))

    # ------------------------------------------------------------------ S3 what is cached
    print('S3  the app shell is cached')
    for path in ('/styles.css', '/script.js', '/settings.js', '/offline.js', '/pwa.js',
                 '/login.html', '/manifest.webmanifest', '/icons/icon-192.png'):
        check(f'{path} is in the cache', cached(path) is True)
    check('the tracker page itself is cached', cached('/index.html') is True)

    # ------------------------------------------------------------------ S4 data stays with offline.js
    print('S4  the worker keeps out of the data layer')
    t.cdp.goto('/history.html')
    cdp.wait("document.getElementById('historyList') !== null")
    cdp.pause(0.5)
    check('no /api/ response was cached', cached('/api/workouts') is False)
    check('history still loaded its workouts from the server',
          cdp.ev("document.querySelectorAll('#historyList li:not(.empty)').length") >= 3)

    # ------------------------------------------------------------------ S5 theme colour
    print('S5  the browser chrome follows the theme')
    cdp.goto('/index.html')
    cdp.wait("typeof getWorkoutSettings === 'function'")
    cdp.pause(0.4)
    light = cdp.ev("document.querySelector('meta[name=theme-color]').content")
    check('light theme sets a light theme-color', light.lower() == '#f4f7fb', str(light))
    cdp.ev("document.documentElement.dataset.theme = 'dark'")
    cdp.pause(0.3)
    dark = cdp.ev("document.querySelector('meta[name=theme-color]').content")
    check('switching to dark updates it', dark.lower() == '#151923', str(dark))

    # ------------------------------------------------------------------ S6 signing out still works
    print('S6  the worker does not break the sign-in redirect')
    cdp.send('Network.clearBrowserCookies')
    cdp.goto('/index.html')
    cdp.pause(0.5)
    path = cdp.ev('location.pathname')
    check('a signed-out visit still reaches the login page', path == '/login.html', str(path))
    still = cached('/index.html')
    check('and the login page did not overwrite the cached tracker', still is True)

    t.set_cookie(t.token)
    cdp.goto('/index.html')
    cdp.wait("document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
    check('signing back in loads the tracker again',
          cdp.ev("document.querySelectorAll('#templateList [data-template-action=start]').length") >= 3)

    # ------------------------------------------------------------------ S7 deploys
    print('S7  a deploy reaches the very next load')
    cache_name = cdp.ev("caches.keys().then(names => names.find(n => n.startsWith('workout-tracker-')))")
    # Stand in for a previous deploy: the cache holds an old pwa.js, the server a newer one.
    cdp.ev(f"caches.open({json.dumps(cache_name)}).then(c => c.put('/pwa.js', new Response('window.__staleShell = true;', "
           "{ headers: { 'Content-Type': 'text/javascript' } }))).then(() => true)")
    check('the cache holds the outdated script',
          'staleShell' in (cdp.ev("caches.match('/pwa.js').then(r => r.text())") or ''))
    cdp.goto('/index.html')
    cdp.wait("typeof getWorkoutSettings === 'function'")
    cdp.pause(0.5)
    check('the next load runs the current script, not the cached one', cdp.ev('window.__staleShell === undefined') is True)
    check('and the cache is refreshed with it',
          cdp.wait("caches.match('/pwa.js').then(r => r.text()).then(text => text.includes('serviceWorker'))"))
    cdp.goto('/')
    cdp.wait("document.querySelectorAll('#templateList [data-template-action=start]').length >= 3")
    cdp.pause(0.4)
    keys = cdp.ev(f"caches.open({json.dumps(cache_name)}).then(c => c.keys()).then(r => r.map(q => new URL(q.url).pathname))") or []
    check('/ shares the cached /index.html instead of adding a second copy', '/' not in keys and '/index.html' in keys, str(keys))

    # ------------------------------------------------------------------ S8 the real thing
    print('S8  a reload with the server gone still opens the app')
    t.server.stop()
    t.server.process.wait(timeout=10)

    def refuses():
        probe = socket.socket()
        probe.settimeout(0.5)
        try:
            probe.connect(('127.0.0.1', t.port))
            return False
        except OSError:
            return True
        finally:
            probe.close()

    # kill() only asks; nothing below proves anything until the port actually refuses.
    check('the server is really down', t.wait_for(refuses, timeout=10))

    # A query string never requested before: Chrome's own HTTP cache cannot hold it, so
    # anything that renders here came from the service worker.
    cdp.goto('/index.html?offline-proof=1')
    cdp.pause(0.6)
    check('the page still renders offline',
          cdp.ev("document.querySelector('.site-nav') !== null") is True)
    check('it is the tracker, not an error page',
          cdp.ev('document.title') == 'Workout Tracker', str(cdp.ev('document.title')))
    check('the templates are usable offline',
          cdp.ev("document.querySelectorAll('#templateList [data-template-action=start]').length") >= 3)
