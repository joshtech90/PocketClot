#!/usr/bin/env python3
"""Einmaliger Telegram-Bot-Lauf, als lilith ohne sudo und ohne Server-DB."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import ssl
import sys
import urllib.parse
import urllib.request
from cryptography.exceptions import InvalidSignature
import pocketclot_transport as t


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Telegram-Redirect gesperrt')


class Bot:
    def __init__(self, cfg):
        self.cfg = cfg
        if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', cfg['bot_token']):
            raise ValueError('Botkonfiguration ungueltig')
        self.base = 'https://api.telegram.org/bot' + cfg['bot_token'] + '/'
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                           urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def request(self, url, data=None, content_type=None, maximum=2 * 1024**2):
        if urllib.parse.urlsplit(url).hostname != 'api.telegram.org' or not url.startswith('https://api.telegram.org/'):
            raise ValueError('Netzziel gesperrt')
        req = urllib.request.Request(url, data=data,
                    headers={'Content-Type': content_type} if content_type else {})
        with self.opener.open(req, timeout=60) as response:
            raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError('Telegram-Antwort zu gross')
        return raw

    def call(self, method, params=None):
        raw = self.request(self.base + method, urllib.parse.urlencode(params or {}).encode(),
                           'application/x-www-form-urlencoded')
        d = json.loads(raw)
        if not d.get('ok'):
            raise RuntimeError('Telegram-Anfrage gescheitert')
        return d['result']

    def download(self, document):
        if not 0 < document.get('file_size', 0) <= t.PART + t.HEADER:
            raise ValueError('Transportdatei zu gross')
        f = self.call('getFile', {'file_id': document['file_id']})
        path = f['file_path']
        if not re.fullmatch(r'[A-Za-z0-9_/-]+\.[A-Za-z0-9]+', path) or '..' in path:
            raise ValueError('Telegram-Dateipfad ungueltig')
        return self.request('https://api.telegram.org/file/bot' + self.cfg['bot_token'] + '/' + path,
                            maximum=t.PART + t.HEADER)

    def send(self, name, wire):
        if not re.fullmatch(r'[0-9]+-[0-9]{4}\.pct', name) or len(wire) > t.PART + t.HEADER:
            raise ValueError('Transportdatei ungueltig')
        import secrets
        boundary = secrets.token_hex(24)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="chat_id"\r\n\r\n'
                f'{self.cfg["chat_id"]}\r\n--{boundary}\r\nContent-Disposition: form-data; '
                f'name="document"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
        body += wire + f'\r\n--{boundary}--\r\n'.encode()
        d = json.loads(self.request(self.base + 'sendDocument', body, 'multipart/form-data; boundary=' + boundary))
        if not d.get('ok') or d['result']['chat']['id'] != self.cfg['chat_id']:
            raise RuntimeError('Telegram-Versand nicht bestaetigt')


class Service:
    def __init__(self, cfg, root, wissen, bot):
        self.cfg, self.root, self.wissen, self.bot = cfg, Path(root), Path(wissen), bot

    def entry(self):
        t.no_links(self.wissen / 'konten.json')
        e = t.read_json(self.wissen / 'konten.json')['konten'].get(self.cfg['account'])
        if not isinstance(e, dict) or e.get('paket') != 'clivia.paket':
            raise ValueError('Kontobindung fuer Zielpaket fehlt')
        return e

    def apply(self, raw, meta):
        self.entry()
        t.atomic(self.wissen / 'clivia.paket', raw)
        # Originalserver liest als anderer Nutzer nur den verschluesselten Text.
        (self.wissen / 'clivia.paket').chmod(0o644)

    def publish(self, raw, kind):
        seq = t.sequence(self.root / 'sequence.json')
        for name, wire in t.documents(raw, kind, self.cfg['account'], self.cfg['sign_private'], seq):
            self.bot.send(name, wire)

    def run(self):
        self.entry()
        me = self.bot.call('getMe')
        if me['id'] != self.cfg['bot_sender_id'] or not me.get('is_bot'):
            raise ValueError('Falscher Transportbot')
        member = self.bot.call('getChatMember', {'chat_id': self.cfg['chat_id'], 'user_id': me['id']})
        if member['status'] not in ('member', 'administrator', 'creator'):
            raise ValueError('Transportbot ist kein Gruppenmitglied')
        if member['status'] not in ('administrator', 'creator') and not me.get('can_read_all_group_messages'):
            raise ValueError('Bot braucht Adminstatus oder deaktivierten Privacy-Modus')
        receiver = t.Receiver(self.cfg, self.root / 'wissen', 'wissen', 'user_sender_id', self.apply)
        cursor_path = self.root / 'cursor.json'
        cursor = t.read_json(cursor_path, {'offset': 0})['offset']
        # Bot-API-Updates verfallen nach 24 h. Erst alle wartenden Seiten holen.
        for _ in range(100):
            updates = self.bot.call('getUpdates', {'offset': cursor, 'timeout': 0, 'limit': 100,
                                                   'allowed_updates': '["message"]'})
            for update in updates:
                m = update.get('message', {})
                if (m.get('chat', {}).get('id') == self.cfg['chat_id']
                        and m.get('from', {}).get('id') == self.cfg['user_sender_id']
                        and not m.get('from', {}).get('is_bot') and not m.get('sender_chat')
                        and not m.get('forward_origin') and not m.get('forward_date')
                        and m.get('document')):
                    try:
                        raw = self.bot.download(m['document'])
                        receiver.accept(self.cfg['chat_id'], m['from']['id'], raw)
                    except (ValueError, KeyError, TypeError, InvalidSignature):
                        pass
                cursor = update['update_id'] + 1
                t.atomic(cursor_path, t.canonical({'offset': cursor}))
            if len(updates) < 100:
                break
        else:
            raise RuntimeError('Zu viele wartende Telegram-Updates')
        entry = self.entry()
        active = entry.get('export') is True
        export_hash = None
        if active:
            # Kein glob, keine fremde Exportdatei und keine Nutzdaten-DB.
            p = self.wissen / 'aus' / (self.cfg['account'] + '.export')
            t.no_links(p)
            if p.stat().st_size > t.LIMITS['export']:
                raise ValueError('Export zu gross')
            raw = p.read_bytes()
            if not raw.startswith(b'PCX1'):
                raise ValueError('Exportformat ungueltig')
            export_hash = t.digest(raw)
            sent_path = self.root / 'sent.json'
            if t.read_json(sent_path, {}).get('hash') != export_hash:
                self.publish(raw, 'export')
                t.atomic(sent_path, t.canonical({'hash': export_hash}))
            # Ein waehrend des Lesens erfolgter Widerruf darf keinen aktiven Status liefern.
            t.no_links(p)
            with p.open('rb') as f:
                current = f.read(t.LIMITS['export'] + 1)
            if self.entry() != entry or t.digest(current) != export_hash:
                raise RuntimeError('Export oder Kontofreigabe waehrend Lauf geaendert')
        self.publish(b'PCS1' + t.canonical({'active': active, 'export_hash': export_hash}), 'status')


def main():
    a = argparse.ArgumentParser()
    a.add_argument('--config', type=Path, default=Path.home()/'.config/clivia/telegram-transport.json')
    a.add_argument('--state', type=Path, default=Path.home()/'clivia-telegram/state')
    a.add_argument('--wissen', type=Path, default=Path('/opt/pocket-claude/wissen'))
    args = a.parse_args()
    try:
        cfg = t.config(args.config)
        with t.lock(args.state / 'lauf.lock'):
            Service(cfg, args.state, args.wissen, Bot(cfg)).run()
    except Exception as e:
        # HTTP-Exceptions enthalten Bot-Token in URL. Niemals Exceptiontext loggen.
        print('Telegram-Transport gescheitert (' + type(e).__name__ + ').', file=sys.stderr)
        return 1
    print('Telegram-Transport erfolgreich.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
