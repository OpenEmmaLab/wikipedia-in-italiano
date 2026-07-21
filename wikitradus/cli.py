"""Prerequisiti: la CLI di traduzione e l'autenticazione a GitHub."""
import shutil
import subprocess
import sys

# Le due CLI supportate, con il modo di invocarle non interattivamente.
ASSISTANTS = [
    ("claude", lambda prompt: ["claude", "-p", prompt]),
    ("codex", lambda prompt: ["codex", "exec", prompt]),
]

PROBE_PROMPT = "Rispondi esattamente OK"
PROBE_TIMEOUT = 120
TRANSLATE_TIMEOUT = 900


class PrerequisiteError(Exception):
    """Un prerequisito non è soddisfatto: lo script non può proseguire."""


def _run(command, timeout):
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, check=False
    )


class Assistant:
    """La CLI che esegue le traduzioni: `claude` oppure `codex`."""

    def __init__(self, name, build_command):
        self.name = name
        self._build = build_command

    def ask(self, prompt, timeout=TRANSLATE_TIMEOUT, cwd=None):
        result = subprocess.run(
            self._build(prompt), capture_output=True, text=True,
            timeout=timeout, cwd=cwd, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "la CLI ha fallito")
        return result.stdout.strip()

    def probe(self):
        """Verifica che la CLI risponda davvero, non solo che esista.

        Non basta che il comando sia nel PATH o che un file di credenziali sia
        presente: una sessione può essere scaduta. `codex` intercala righe di
        servizio nell'output, quindi si cerca OK fra le righe invece di
        pretendere una corrispondenza esatta.
        """
        try:
            answer = self.ask(PROBE_PROMPT, timeout=PROBE_TIMEOUT)
        except (subprocess.TimeoutExpired, RuntimeError):
            return False
        return any(line.strip().upper() == "OK" for line in answer.splitlines())


def find_assistant():
    """Trova claude o codex nel PATH e ne verifica l'autenticazione."""
    available = [
        Assistant(name, build) for name, build in ASSISTANTS
        if shutil.which(name)
    ]
    if not available:
        raise PrerequisiteError(
            "Serve 'claude' oppure 'codex' installato e raggiungibile nel PATH.\n"
            "  Claude Code: https://claude.com/claude-code\n"
            "  Codex:       https://developers.openai.com/codex/cli"
        )

    for assistant in available:
        print(f"Verifico che '{assistant.name}' risponda…", flush=True)
        if assistant.probe():
            print(f"  '{assistant.name}' pronto.")
            return assistant
        print(f"  '{assistant.name}' non risponde: provo ad autenticarlo.")
        # Il login apre il browser e chiede di incollare un codice: è
        # interattivo, quindi eredita il terminale invece di catturare l'output.
        subprocess.run([assistant.name, "login"], check=False)
        if assistant.probe():
            print(f"  '{assistant.name}' pronto.")
            return assistant

    raise PrerequisiteError(
        "Nessuna CLI risponde all'interrogazione di prova.\n"
        "Autenticati manualmente (es. 'claude login') e rilancia: senza un\n"
        "assistente funzionante non ha senso prenotare un gruppo di voci."
    )


def ensure_github_login():
    """Verifica il login a GitHub, avviandolo se manca. È bloccante."""
    if not shutil.which("gh"):
        raise PrerequisiteError(
            "Serve la CLI di GitHub 'gh': https://cli.github.com"
        )
    if _run(["gh", "auth", "status"], timeout=60).returncode == 0:
        return

    print("Non risulti autenticato su GitHub: apro il browser.", flush=True)
    subprocess.run(
        ["gh", "auth", "login", "--web", "--git-protocol", "https"], check=False
    )
    if _run(["gh", "auth", "status"], timeout=60).returncode != 0:
        raise PrerequisiteError(
            "Login a GitHub non riuscito.\n"
            "Senza accesso a GitHub non si può creare il fork, prenotare il\n"
            "gruppo, pubblicare il lavoro né aprire la pull request."
        )


def check_prerequisites():
    """Verifica tutto ciò che serve prima di prenotare un gruppo."""
    assistant = find_assistant()
    ensure_github_login()
    return assistant
