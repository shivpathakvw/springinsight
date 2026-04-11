/**
 * SpringInsight VS Code Extension
 *
 * Provides SpringInsight scan integration directly inside VS Code:
 *   - Scan current project via command palette or context menu
 *   - Show findings as diagnostics (Problems panel + gutter icons)
 *   - Live scan progress in status bar
 *   - Panel views for findings, scan history, and agent configuration
 *   - Inline file annotations for found issues
 */

import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import * as http from 'http';

// ── Types ─────────────────────────────────────────────────────────────────────

interface Finding {
  id: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
  category: string;
  agent_id: string;
  file?: string;
  line?: number;
  problem: string;
  fix?: string;
  effort_hours?: number;
}

interface ScanResult {
  run_id: string;
  project_name: string;
  status: string;
  score_overall?: number;
  score_security?: number;
  agents_completed: string[];
  findings?: Finding[];
}

// ── State ─────────────────────────────────────────────────────────────────────

let diagnosticCollection: vscode.DiagnosticCollection;
let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;
let webUiProcess: cp.ChildProcess | null = null;
let currentRunId: string | null = null;

// ── Severity helpers ─────────────────────────────────────────────────────────

function severityToDiagnostic(sev: string): vscode.DiagnosticSeverity {
  switch (sev) {
    case 'CRITICAL':
    case 'HIGH':
      return vscode.DiagnosticSeverity.Error;
    case 'MEDIUM':
      return vscode.DiagnosticSeverity.Warning;
    case 'LOW':
      return vscode.DiagnosticSeverity.Information;
    default:
      return vscode.DiagnosticSeverity.Hint;
  }
}

function severityIcon(sev: string): string {
  switch (sev) {
    case 'CRITICAL': return '🔴';
    case 'HIGH':     return '🟠';
    case 'MEDIUM':   return '🟡';
    case 'LOW':      return '🔵';
    default:         return '⚪';
  }
}

// ── Web UI communication ──────────────────────────────────────────────────────

function getWebUiUrl(): string {
  const config = vscode.workspace.getConfiguration('springinsight');
  return config.get<string>('webUiUrl', 'http://127.0.0.1:8080');
}

async function fetchWebUi(path: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const url = `${getWebUiUrl()}${path}`;
    http.get(url, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          resolve(JSON.parse(data));
        } catch {
          resolve(data);
        }
      });
    }).on('error', reject);
  });
}

async function postWebUi(path: string, body: object): Promise<any> {
  return new Promise((resolve, reject) => {
    const json = JSON.stringify(body);
    const urlBase = new URL(getWebUiUrl());
    const opts = {
      hostname: urlBase.hostname,
      port: parseInt(urlBase.port || '8080'),
      path,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(json) },
    };
    const req = http.request(opts, (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch { resolve(data); }
      });
    });
    req.on('error', reject);
    req.write(json);
    req.end();
  });
}

// ── Ensure Web UI is running ──────────────────────────────────────────────────

async function ensureWebUiRunning(): Promise<boolean> {
  try {
    await fetchWebUi('/health');
    return true;
  } catch {
    // Not running — try to start it
    const config = vscode.workspace.getConfiguration('springinsight');
    if (!config.get<boolean>('autoStartWebUi', true)) {
      vscode.window.showWarningMessage(
        'SpringInsight Web UI is not running. Start it with: springinsight web',
        'Start Now'
      ).then(sel => {
        if (sel === 'Start Now') startWebUi();
      });
      return false;
    }
    return startWebUi();
  }
}

function startWebUi(): Promise<boolean> {
  return new Promise((resolve) => {
    outputChannel.show(true);
    outputChannel.appendLine('Starting SpringInsight Web UI…');

    webUiProcess = cp.spawn('springinsight', ['web'], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    webUiProcess.stdout?.on('data', (d) => outputChannel.append(d.toString()));
    webUiProcess.stderr?.on('data', (d) => outputChannel.append(d.toString()));

    // Wait up to 8 seconds for the server to be ready
    let attempts = 0;
    const check = setInterval(async () => {
      attempts++;
      try {
        await fetchWebUi('/health');
        clearInterval(check);
        outputChannel.appendLine('✓ Web UI ready');
        resolve(true);
      } catch {
        if (attempts >= 16) {
          clearInterval(check);
          outputChannel.appendLine('✗ Web UI did not start in time');
          resolve(false);
        }
      }
    }, 500);
  });
}

// ── Diagnostics (Problems panel) ─────────────────────────────────────────────

function applyFindingsDiagnostics(projectPath: string, findings: Finding[]): void {
  diagnosticCollection.clear();

  const byFile = new Map<string, vscode.Diagnostic[]>();

  for (const f of findings) {
    if (!f.file) continue;

    const filePath = path.isAbsolute(f.file)
      ? f.file
      : path.join(projectPath, f.file);
    const uri = vscode.Uri.file(filePath);
    const key = uri.toString();

    const line = Math.max(0, (f.line || 1) - 1);
    const range = new vscode.Range(line, 0, line, 999);

    const diagnostic = new vscode.Diagnostic(
      range,
      `${severityIcon(f.severity)} [${f.agent_id}] ${f.problem}`,
      severityToDiagnostic(f.severity),
    );
    diagnostic.source = `SpringInsight (${f.agent_id})`;
    diagnostic.code = f.category;

    if (!byFile.has(key)) byFile.set(key, []);
    byFile.get(key)!.push(diagnostic);
  }

  byFile.forEach((diags, uriStr) => {
    diagnosticCollection.set(vscode.Uri.parse(uriStr), diags);
  });
}

// ── Status bar ────────────────────────────────────────────────────────────────

function setStatus(text: string, tooltip?: string, spin = false): void {
  statusBarItem.text = `$(${spin ? 'loading~spin' : 'shield'}) ${text}`;
  statusBarItem.tooltip = tooltip || 'SpringInsight';
  statusBarItem.show();
}

// ── Commands ──────────────────────────────────────────────────────────────────

async function cmdScanProject(agents?: string): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders?.length) {
    vscode.window.showErrorMessage('SpringInsight: No workspace folder open.');
    return;
  }

  const projectPath = workspaceFolders[0].uri.fsPath;

  if (!(await ensureWebUiRunning())) return;

  setStatus('Starting scan…', 'SpringInsight: Starting scan', true);
  diagnosticCollection.clear();

  try {
    const config = vscode.workspace.getConfiguration('springinsight');
    const agentList = agents || config.get<string>('defaultAgents', 'all');

    const result = await postWebUi('/api/scan', {
      repo_url: projectPath,
      agents: agentList,
    }) as ScanResult;

    if (!result.run_id) {
      vscode.window.showErrorMessage(`SpringInsight scan failed: ${JSON.stringify(result)}`);
      setStatus('Scan failed', 'SpringInsight: Scan failed');
      return;
    }

    currentRunId = result.run_id;
    setStatus('Scanning…', `Run ID: ${result.run_id}`, true);
    outputChannel.appendLine(`\n▶ Scan started — run_id: ${result.run_id}`);

    // Open the web UI in the browser for live progress
    vscode.env.openExternal(vscode.Uri.parse(`${getWebUiUrl()}/scans/${result.run_id}`));

    // Poll for completion
    await pollForCompletion(result.run_id, projectPath);

  } catch (err: any) {
    vscode.window.showErrorMessage(`SpringInsight error: ${err.message}`);
    setStatus('Error', err.message);
  }
}

async function pollForCompletion(runId: string, projectPath: string): Promise<void> {
  let attempts = 0;
  const maxAttempts = 120;  // 10 minutes at 5s intervals

  const check = async () => {
    attempts++;
    try {
      const run = await fetchWebUi(`/api/runs/${runId}`);

      if (run.status === 'complete') {
        const score = run.scores?.overall ?? '?';
        setStatus(`Score: ${score}/100`, `SpringInsight: ${run.project_name} — ${score}/100`);
        outputChannel.appendLine(`✓ Scan complete — score: ${score}/100`);

        // Load findings and apply as diagnostics
        try {
          const data = await fetchWebUi(`/api/runs/${runId}/findings`);
          if (Array.isArray(data)) {
            applyFindingsDiagnostics(projectPath, data);
            const critHigh = data.filter(f => f.severity === 'CRITICAL' || f.severity === 'HIGH').length;
            vscode.window.showInformationMessage(
              `SpringInsight: ${data.length} findings (${critHigh} critical/high). Score: ${score}/100`,
              'View Report', 'Show Problems'
            ).then(sel => {
              if (sel === 'View Report') {
                vscode.env.openExternal(vscode.Uri.parse(`${getWebUiUrl()}/scans/${runId}/report`));
              } else if (sel === 'Show Problems') {
                vscode.commands.executeCommand('workbench.action.problems.focus');
              }
            });
          }
        } catch { /* findings load failed */ }

      } else if (run.status === 'failed') {
        setStatus('Scan failed', run.error || 'Scan failed');
        vscode.window.showErrorMessage(`SpringInsight scan failed: ${run.error || 'unknown error'}`);

      } else if (attempts < maxAttempts) {
        // Still running — check again in 5 seconds
        const done = Object.values((run.agents || {})).filter((s: any) => s === 'complete' || s === 'failed').length;
        const total = Object.keys((run.agents || {})).length;
        setStatus(`Scanning ${done}/${total}…`, `Run: ${runId}`, true);
        setTimeout(check, 5000);
      } else {
        setStatus('Scan timeout', 'SpringInsight: timed out polling');
      }
    } catch {
      if (attempts < maxAttempts) {
        setTimeout(check, 5000);
      }
    }
  };

  setTimeout(check, 3000);
}

async function cmdOpenDashboard(): Promise<void> {
  if (!(await ensureWebUiRunning())) return;
  vscode.env.openExternal(vscode.Uri.parse(getWebUiUrl()));
}

async function cmdShowFindings(): Promise<void> {
  if (!currentRunId) {
    vscode.window.showInformationMessage('No recent scan. Run a scan first.');
    return;
  }
  vscode.env.openExternal(vscode.Uri.parse(`${getWebUiUrl()}/scans/${currentRunId}/report`));
}

function cmdClearDiagnostics(): void {
  diagnosticCollection.clear();
  setStatus('Ready', 'SpringInsight');
}

// ── Extension lifecycle ───────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
  diagnosticCollection = vscode.languages.createDiagnosticCollection('springinsight');
  outputChannel = vscode.window.createOutputChannel('SpringInsight');

  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBarItem.command = 'springinsight.openDashboard';
  setStatus('Ready', 'SpringInsight — click to open dashboard');

  // Register commands
  const cmds: [string, (...args: any[]) => any][] = [
    ['springinsight.scanProject',    () => cmdScanProject()],
    ['springinsight.scanPhase1',     () => cmdScanProject('A03,A10,A12')],
    ['springinsight.openDashboard',  cmdOpenDashboard],
    ['springinsight.showFindings',   cmdShowFindings],
    ['springinsight.clearDiagnostics', cmdClearDiagnostics],
    ['springinsight.configureAgents', () => {
      ensureWebUiRunning().then(ok => {
        if (ok) vscode.env.openExternal(vscode.Uri.parse(`${getWebUiUrl()}/settings/agents`));
      });
    }],
  ];

  for (const [id, handler] of cmds) {
    context.subscriptions.push(vscode.commands.registerCommand(id, handler));
  }

  context.subscriptions.push(diagnosticCollection, statusBarItem, outputChannel);

  outputChannel.appendLine('SpringInsight extension activated.');
  outputChannel.appendLine(`Web UI expected at: ${getWebUiUrl()}`);
  outputChannel.appendLine('Run: springinsight web   to start the backend.');
}

export function deactivate(): void {
  if (webUiProcess) {
    webUiProcess.kill();
    webUiProcess = null;
  }
}
