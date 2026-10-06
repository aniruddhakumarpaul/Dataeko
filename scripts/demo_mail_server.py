"""Loopback-only SMTP and private tenant email inbox for local development."""
from email import policy
from email.parser import BytesParser
import html
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse, quote

from aiosmtpd.controller import Controller
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from triage.tickets import TicketStore
from triage.mail import MailService
from triage.accounts import AccountService
from triage.mailboxes import MailboxService

store = TicketStore(os.getenv('SUPPORT_DB_PATH', str(ROOT / 'var' / 'support.sqlite3')))
mail_service = MailService(store, ROOT)
AccountService(store, mail_service)
mailboxes = MailboxService(store)


def continuation(path):
    value = parse_qs(urlparse(path).query).get('continue', [''])[0]
    return value if len(value)==32 and all(c in '0123456789abcdef' for c in value) else ''


class Mailbox:
    async def handle_DATA(self, server, session, envelope):
        mail = BytesParser(policy=policy.default).parsebytes(envelope.content)
        body = mail.get_body(preferencelist=('plain',))
        text = body.get_content() if body else ''
        accepted = [mailboxes.receive(recipient, str(mail['Subject'] or ''), text) for recipient in envelope.rcpt_tos]
        return '250 Stored in the private demo mailbox' if all(accepted) else '550 This local demo mailbox is not provisioned'


class Viewer(BaseHTTPRequestHandler):
    def cookies(self):
        parsed = SimpleCookie()
        try:
            parsed.load(self.headers.get('Cookie',''))
        except Exception:
            return {}
        return {key:value.value for key,value in parsed.items()}

    def reply(self, page, *, status=200, cookies=()):
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options','nosniff')
        for cookie in cookies:
            self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(page.encode())

    def page(self, error=''):
        code = continuation(self.path)
        back = 'http://127.0.0.1:8501/' + ('?auth_challenge='+quote(code) if code else '')
        path = '/?continue='+quote(code) if code else '/'
        principal = mailboxes.resolve_session(self.cookies().get('mailbox_session',''))
        csrf = mailboxes.csrf_token()
        entries = []
        if principal:
            for item in mailboxes.messages(principal):
                entries.append(f"<article><h2>{html.escape(item['subject'])}</h2><pre>{html.escape(item['body'])}</pre></article>")
            content = f"<p>Signed in as <strong>{html.escape(principal.email)}</strong></p>" + ''.join(entries)
            if not entries:
                content += '<article><h2>No emails yet</h2><p>Return to support and request an email code, then refresh this inbox.</p></article>'
            content += f"<form action='/logout' method='post'><input type='hidden' name='csrf' value='{csrf}'><input type='hidden' name='continue' value='{code}'><button>Sign out</button></form>"
        else:
            content = f"""<article><h2>Sign in to your inbox</h2><p>Use your assigned email and separate mailbox password.</p>
            <form action='/login' method='post'><input type='hidden' name='csrf' value='{csrf}'>
            <input type='hidden' name='continue' value='{code}'>
            <label>Email address<input name='email' type='email' autocomplete='username' required maxlength='254'></label>
            <label>Mailbox password<input name='password' type='password' autocomplete='current-password' required></label>
            <button>Sign in</button></form></article>"""
        page = f"""<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>
        <title>Dataeko demo mailbox</title><style>
        body{{font:16px system-ui;max-width:850px;margin:40px auto;padding:0 20px;background:#f8faf9;color:#18241f}}
        article{{background:white;border:1px solid #ddd;border-radius:10px;padding:20px;margin:20px 0}}
        pre{{white-space:pre-wrap;font:inherit}} h2,p,pre{{overflow-wrap:anywhere}} a{{color:#246b55}}
        nav a,button{{display:inline-block;padding:10px 14px;border:1px solid #246b55;border-radius:8px;text-decoration:none;margin:0 12px 8px 0}}
        button{{background:#246b55;color:white;cursor:pointer;font:inherit}} label{{display:block;margin:16px 0}}
        input:not([type=hidden]){{display:block;width:100%;box-sizing:border-box;margin-top:8px;padding:12px;border:1px solid #bbb;border-radius:6px;font:inherit}}
        .error{{color:#a51b1b}}
        </style><nav><a href='{html.escape(back)}'>← Back to support</a><a href='{html.escape(path)}'>Refresh inbox</a></nav>
        <h1>Dataeko demo mailbox</h1><p>Private tenant inbox · local demo only. No internet email delivery.</p>
        <p class='error' role='alert'>{html.escape(error)}</p>{content}"""
        self.reply(page,cookies=(f'mailbox_csrf={csrf}; HttpOnly; SameSite=Strict; Path=/',))

    def do_GET(self):
        if urlparse(self.path).path != '/':
            self.reply('Not found',status=404)
            return
        self.page()

    def do_POST(self):
        if self.headers.get('Origin') not in {'http://127.0.0.1:8025','http://localhost:8025'}:
            self.reply('Request origin rejected.',status=403)
            return
        try:
            length = int(self.headers.get('Content-Length','0'))
        except ValueError:
            self.reply('Invalid request.',status=400)
            return
        if not 0 < length <= 4096:
            self.reply('Invalid request.',status=400)
            return
        data = parse_qs(self.rfile.read(length).decode('utf-8',errors='replace'))
        cookies = self.cookies()
        if not mailboxes.valid_csrf(cookies.get('mailbox_csrf',''),data.get('csrf',[''])[0]):
            self.reply('Please refresh and try again.',status=403)
            return
        code = data.get('continue',[''])[0]
        code = code if len(code)==32 and all(c in '0123456789abcdef' for c in code) else ''
        cookie = ''
        if self.path == '/login':
            try:
                token = mailboxes.sign_in(data.get('email',[''])[0],data.get('password',[''])[0])
            except ValueError as error:
                self.path = '/?continue='+code
                self.page(str(error))
                return
            cookie = f'mailbox_session={token}; HttpOnly; SameSite=Strict; Path=/'
        elif self.path == '/logout':
            mailboxes.logout(cookies.get('mailbox_session',''))
            cookie = 'mailbox_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/'
        else:
            self.reply('Not found',status=404)
            return
        self.send_response(303)
        self.send_header('Location','/?continue='+code)
        self.send_header('Set-Cookie',cookie)
        self.end_headers()

    def log_message(self,*args):
        pass


if __name__ == '__main__':
    controller = Controller(Mailbox(),hostname='127.0.0.1',port=1025,data_size_limit=200000)
    controller.start()
    print('Local SMTP: 127.0.0.1:1025; private demo inbox: http://127.0.0.1:8025',flush=True)
    try:
        ThreadingHTTPServer(('127.0.0.1',8025),Viewer).serve_forever()
    finally:
        controller.stop()
