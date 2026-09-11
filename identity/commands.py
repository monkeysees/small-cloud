"""Delivered CLI definitions shared by parsing, help and the offline catalog."""
import argparse
from typing import Any

from .common import Failure


def argument(name, description, **options):
    return {'name': name, 'description': description, **options}


APP = argument('app', 'Workspace-unique app name.')
WAIT = argument('--wait', 'Wait for completion; otherwise return acceptance.', action='store_true')
TIMEOUT = argument('--timeout', 'Positive wait bound in seconds.', type='integer', default=900)
ACK = argument('--acknowledge-secret-authority', 'Allow workspace members to trigger actions using app secrets.', action='store_true')
GLOBALS = [argument('--json', 'Emit one schema_version: 1 JSON envelope; never prompt.', action='store_true'),
    argument('--no-input', 'Prohibit terminal prompts.', action='store_true'),
    argument('--no-color', 'Use output without color (also the default).', action='store_true'),
    argument('--request-id', 'Mutation retry UUID; operation status accepts this instead of an ID.'),
    argument('--workspace', 'Target workspace ID or exact unambiguous name; overrides the saved default.'),
    argument('--version', 'Print installed CLI version.', action='version', version='small-cloud 0.3.1')]


def command(path, description, example, permission, outputs, effects='Read only.', inputs=(), guide='getting-started', **dispatch) -> dict[str, Any]:
    return dict(path=path, description=description, examples=['small-cloud ' + example],
                permissions=permission, outputs=outputs, effects=effects, inputs=list(inputs),
                guide=guide, dispatch=dispatch)


COMMANDS = [
    command('workspace create', 'Create a workspace with one designated owner.',
            'workspace create "Design team" --owner owner@example.com --json', 'Platform administrator.',
            'workspace: id, name, owner_id.', 'Creates a workspace and admits its owner as administrator and creator.',
            [argument('name', 'Workspace display name.'), argument('--owner', 'Exact Google email of the owner.', required=True)],
            guide='workspace', command='workspace', action='create'),
    command('workspace list', 'List your accessible workspaces and saved default.',
            'workspace list --json', 'Authenticated identity.', 'workspaces with roles, default_workspace.',
            guide='workspace', command='workspace', action='list'),
    command('workspace select', 'Save the default workspace for your identity on this service.',
            'workspace select ws_FROM_LIST --json', 'Member of the target workspace.',
            'workspace, default_workspace.', 'Changes the saved default across CLI credentials.',
            [argument('target', 'Workspace ID or exact unambiguous name.')],
            guide='workspace', command='workspace', action='select'),
    command('app list', 'List accessible apps with descriptions, creators and URLs.', 'app list --json',
            'Workspace member; only accessible apps are returned.',
            'apps: array of {name, description, creator, url}.', command='directory', action='directory'),
    command('app status', 'Inspect availability, deployment and cleanup status.', 'app status example --json',
            'App creator or workspace administrator; no private content access.',
            'App identity, availability, active_deployment_id, latest_operation, cleanup and runtime_error.',
            inputs=[APP], command='status', action='status'),
    command('app check', 'Check source locally before upload; does not establish remote build feasibility or readiness.',
            'app check . --json', 'None; offline, no Docker required.',
            'summary, included/excluded paths, total_bytes, limits, source_rules, verified_locally and requires_remote.',
            'Reads and packages source in memory; no upload, authentication, file writes or build allowance consumption.',
            [argument('folder', 'Local source folder containing Dockerfile.')],
            guide='runtime', command='check', action='check'),
    command('app deploy', 'Upload a Dockerfile source folder; acceptance does not mean ready. Use --wait for completion.',
            'app deploy . --name example --description demo --wait --json', 'Creator; updates require app ownership.',
            'operation_id, app, url and state; --dry-run returns included/excluded paths and total_bytes.',
            'Uploads source and builds; consumes allowance. Dry run is local only.',
            [argument('folder', 'Local source folder containing Dockerfile.'),
             argument('--name', 'Immutable lowercase app slug, at most 63 characters.', required=True),
             argument('--description', 'Up to 500 characters; required for new apps, omitted updates preserve it.'),
             argument('--dry-run', 'Validate and list upload contents without uploading.', action='store_true'), WAIT, TIMEOUT],
            guide='publishing', command='deploy', action='deploy'),
    command('app logs', 'Read a bounded build or runtime log snapshot (no live following).',
            'app logs example --source runtime --json', 'App creator or workspace administrator.',
            'entries, next_cursor, truncated, dropped_bytes, collection_interrupted and oldest_available_at.',
            inputs=[APP, argument('--source', 'Log stream.', choices=['build', 'runtime'], required=True),
                    argument('--deployment', 'Build deployment ID; build source only.'),
                    argument('--since', 'UTC RFC3339 lower bound; exclusive with --cursor.', exclusive='position'),
                    argument('--cursor', 'Continuation from an earlier snapshot; exclusive with --since.', exclusive='position'),
                    argument('--limit', 'Maximum entries, 1 to 1000.', type='integer', default=100)],
            guide='publishing', command='logs', action='logs'),
    command('app share', 'Change creator-only or workspace-wide sharing.',
            'app share example --scope workspace-wide --acknowledge-secret-authority --json',
            'App creator only.', 'app, sharing_scope, secret_authority_acknowledged.', 'Changes who may access the app; secrets require acknowledgement.',
            [APP, argument('--scope', 'Audience.', required=True, choices=['creator-only', 'workspace-wide']), ACK],
            guide='secrets-sharing', command='share', action='share'),
    command('app secrets list', 'List saved secret names without value readback.', 'app secrets list example --json',
            'App creator only.', 'names: sorted array of secret names.', inputs=[APP],
            guide='secrets-sharing', command='secret', action='list'),
    command('app secrets set', 'Set a runtime secret from stdin or a hidden terminal prompt.',
            'app secrets set example SERVICE_TOKEN --stdin --wait --json', 'App creator only.',
            'app, changed, operation_id, state; saved values are never returned.',
            'Saves encrypted configuration and restarts the app; acceptance by default.',
            [APP, argument('name', 'Uppercase secret name; PORT, DATABASE_URL and SMALL_CLOUD_* are reserved.'),
             argument('--stdin', 'Read exact UTF-8 value bytes from stdin, including newlines.', action='store_true'), ACK, WAIT, TIMEOUT],
            guide='secrets-sharing', command='secret', action='set'),
    command('app secrets delete', 'Remove a secret; absent names succeed without restart.',
            'app secrets delete example SERVICE_TOKEN --wait --json', 'App creator only.',
            'app, changed, operation_id (omitted for no-op), state.', 'Removes saved configuration and restarts if changed.',
            [APP, argument('name', 'Secret name to remove.'), WAIT, TIMEOUT],
            guide='secrets-sharing', command='secret', action='delete'),
    command('workspace usage', 'Show counts and build seconds. Each build reserves 600 seconds; fewer than ten remaining minutes cannot admit a build.',
            'workspace usage --json', 'Creator or workspace administrator.',
            'creators, deployed_apps, active_apps (used/limit), build (period_start, period_end, limit_seconds, charged_seconds, reserved_seconds, available_seconds).',
            guide='workspace', command='usage', action='usage'),
    command('workspace member add', 'Admit a Google-verified email to the selected workspace.',
            'workspace member add colleague@example.com --json', 'Workspace administrator.',
            'user_id, email, member, creator, administrator.', 'Creates pending admission; existing membership is a no-op.',
            [argument('email', 'Google-verified email to admit.')], guide='workspace', command='admin', resource='member', action='add'),
    command('workspace creator grant', 'Grant an admitted member publishing authority.',
            'workspace creator grant usr_FROM_AUTH_STATUS --json', 'Workspace administrator.',
            'user_id, email, member, creator, administrator.', 'Grants creator privilege subject to the five-creator limit.',
            [argument('user_id', 'User ID returned by the member’s auth status.')],
            guide='workspace', command='admin', resource='creator', action='grant'),
    command('auth login', 'Approve Google sign-in in a browser and save a protected CLI credential.',
            'auth login --no-browser --json', 'Explicitly admitted workspace member; browser approval required.',
            'service_endpoint, user, roles, credential_id, expires_at, workspace, default_workspace, platform_administrator, missing_steps, next_steps; no credential value.',
            'Starts browser approval and saves a credential locally. --no-input prohibits terminal prompts, not browser approval.',
            [argument('--no-browser', 'Print approval URL and code to stderr without opening a browser.', action='store_true')],
            command='auth', action='login'),
    command('auth login start', 'Start browser approval for a headless session without opening a browser.',
            'auth login start --json --no-input', 'Explicitly admitted workspace member approves in a browser.',
            'verification_url, user_code, attempt_id, expires_in, expires_at; no confidential login material.',
            'Saves protected, origin-bound pending state outside source folders; does not save a credential.',
            command='auth', action='login-start'),
    command('auth login finish', 'Wait for approval of a local attempt and save the credential.',
            'auth login finish ATTEMPT_ID --json --no-input', 'Human approval of this local login attempt.',
            'service_endpoint, user, roles, credential_id, expires_at, workspace, default_workspace, platform_administrator, missing_steps, next_steps; no credential value. Pending timeout/interruption includes attempt_id and next_command.',
            'Polls and consumes one-time delivery. Pending attempts survive timeout or interruption until expiry.',
            [argument('attempt_id', 'Local identifier returned by auth login start; never the poll secret.'),
             argument('--timeout', 'Positive wait bound in seconds; at most the remaining login lifetime.', type='integer', default=600)],
            command='auth', action='login-finish'),
    command('auth status', 'Show current identity and workspace without credential values.', 'auth status --json',
            'No credential needed to report missing sign-in; identity requires authentication.',
            'service_endpoint, user, roles, credential_id, expires_at, workspace, default_workspace, platform_administrator, missing_steps, next_steps. Missing sign-in returns AUTH_REQUIRED with setup details.',
            command='auth', action='status'),
    command('auth logout', 'Revoke this CLI credential and remove local storage after server success.',
            'auth logout --json', 'Credential holder.', 'revoked: boolean.',
            'Revokes this credential; offline failure retains local storage for retry.', command='auth', action='logout'),
    command('auth revoke', 'Revoke all your CLI credentials, including this one.', 'auth revoke --all --json',
            'Authenticated credential holder.', 'revoked: boolean.', 'Revokes every CLI credential for the caller and removes the local copy.',
            [argument('--all', 'Confirm revocation of all your CLI credentials.', required=True, action='store_true')], command='auth', action='revoke'),
    command('operation status', 'Observe an operation by ID or original request UUID, exclusively.',
            'operation status op_FROM_DEPLOY --json', 'Operation owner or workspace administrator.',
            'id, operation_id, kind, state, app, deployment_id, request_id, created_at, updated_at, completed_at, error, cleanup_pending.',
            inputs=[argument('id', 'Operation ID; omit when using --request-id.', nargs='?')],
            guide='publishing', command='operation', action='status'),
    command('catalog', 'Query the versioned machine catalog, optionally scoped to a command or group.',
            'catalog app status --json', 'None; offline.', 'catalog_version, scope, commands, global_inputs and response_contract.',
            inputs=[argument('query', 'Command or group path, as words or one quoted string.', nargs='*')], command='catalog', action='catalog'),
    command('guide', 'List bundled offline guides or read one by topic.', 'guide getting-started --json',
            'None; offline.', 'guides: topic/description list, or topic and content.',
            inputs=[argument('topic', 'Guide topic; omit to list available guides.', nargs='?')], command='guide', action='guide'),
]

GROUPS = {
    '': ('Publish and inspect small software. Start with auth login, then app list.', 'getting-started', 'app list --json'),
    'app': ('Publish, inspect and configure apps.', 'publishing', 'app list --json'),
    'app secrets': ('Manage confidential runtime values without saved-value readback.', 'secrets-sharing', 'app secrets list example --json'),
    'workspace': ('Create, select and administer workspaces; inspect usage.', 'workspace', 'workspace list --json'),
    'workspace member': ('Admit workspace members.', 'workspace', 'workspace member add colleague@example.com --json'),
    'workspace creator': ('Grant publishing privileges separately from membership.', 'workspace', 'workspace creator grant usr_FROM_AUTH_STATUS --json'),
    'auth': ('Sign in with browser approval and manage credentials.', 'getting-started', 'auth status --json'),
    'operation': ('Inspect accepted work without issuing a new mutation.', 'publishing', 'operation status op_FROM_DEPLOY --json'),
}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Failure('INVALID_ARGUMENT', message + ' Run small-cloud --help or the command with --help.')


def add_input(parser, item):
    options = {key: value for key, value in item.items() if key not in ('name', 'description', 'exclusive', 'type')}
    if item.get('type') == 'integer':
        options['type'] = int
    parser.add_argument(item['name'], help=item['description'], **options)


def parser():
    parsers, children = {}, {}
    definitions: list[tuple[str, dict[str, Any]]] = [
        (path, dict(description=desc, guide=guide, examples=['small-cloud ' + example]))
        for path, (desc, guide, example) in GROUPS.items()]
    definitions.extend((c['path'], c) for c in COMMANDS)
    for path, definition in definitions:
        epilog = ('Examples:\n  ' + '\n  '.join(definition['examples']) + '\n\n'
                  'Machine output: --json emits one versioned JSON object and disables prompts.\n'
                  'Global flags may appear before or after commands.\n'
                  'Guide: small-cloud guide ' + definition['guide'] + '\n'
                  'Catalog: small-cloud catalog' + (' ' + path if path else '') + ' --json')
        if 'permissions' in definition:
            epilog += '\nPermissions: ' + definition['permissions'] + '\nEffects: ' + definition['effects'] + '\nResult: ' + definition['outputs']
        options: dict[str, Any] = dict(description=definition['description'], epilog=epilog, formatter_class=argparse.RawDescriptionHelpFormatter)
        if not path:
            current = Parser(prog='small-cloud', **options)
            for item in GLOBALS:
                add_input(current, item)
        else:
            parent, _, name = path.rpartition(' ')
            if parent not in children:
                children[parent] = parsers[parent].add_subparsers(required=parent != 'auth login')
            current = children[parent].add_parser(name, help=definition['description'], **options)
        parsers[path] = current
        if 'dispatch' in definition:
            current.set_defaults(**definition['dispatch'], command_path=path)
            exclusive = {}
            for item in definition['inputs']:
                group = item.get('exclusive')
                if group and group not in exclusive:
                    exclusive[group] = current.add_mutually_exclusive_group()
                add_input(exclusive[group] if group else current, item)
    return parsers, children


def help_parser(argv, parsers, children):
    # Skip option values: an app or request ID called "auth" is not a command.
    path, index = '', 0
    while index < len(argv):
        word = argv[index]
        if word == '--':
            break
        current = parsers[path]
        option = current._option_string_actions.get(word)
        if option is None:
            option = parsers['']._option_string_actions.get(word)
        if option is not None:
            index += 1 if option.nargs == 0 else 2
            continue
        if word.startswith('-'):
            index += 1
            continue
        if path not in children or word not in children[path].choices:
            break
        path = (path + ' ' + word).strip()
        index += 1
    return parsers[path]


def catalog(query):
    scope = ' '.join(' '.join(query).split())
    selected = [c for c in COMMANDS if not scope or c['path'] == scope or c['path'].startswith(scope + ' ')]
    if not selected:
        raise Failure('INVALID_ARGUMENT', 'Unknown catalog scope. Run small-cloud catalog --json.')
    return {'catalog_version': 1, 'scope': scope or None,
            'commands': [{key: ([catalog_input(i) for i in value] if key == 'inputs' else value)
                          for key, value in c.items() if key != 'dispatch'} for c in selected],
            'global_inputs': [catalog_input(i) for i in GLOBALS],
            'response_contract': {'schema_version': 1, 'stdout': 'One JSON object with --json; readable text otherwise. Help and version always emit text.',
                'fields': {'schema_version': 'integer', 'ok': 'boolean', 'request_id': 'UUID or null',
                           'data': 'object or null', 'error': '{code,message,retryable,details} or null'},
                'exit_codes': {'0': 'success', '2': 'invalid input', '3': 'authentication',
                               '4': 'authorization', '1': 'other server failure', '5': 'conflict or capacity refusal', '6': 'transient failure', '130': 'interrupted'},
                'prompts': 'Never in JSON/non-TTY mode. Explicit login still requires browser approval.'}}


def catalog_input(item):
    return {**item, 'type': item.get('type', 'boolean' if item.get('action') in ('store_true', 'version') else 'string'),
            'nargs': item.get('nargs', 0 if item.get('action') in ('store_true', 'version') else 1),
            'default': item.get('default', False if item.get('action') == 'store_true' else None),
            'required': item.get('required', not item['name'].startswith('-') and item.get('nargs') not in ('?', '*'))}


def guide(topic):
    from .guides import GUIDES
    if not topic:
        return {'guides': [{'topic': key, 'description': value[0]} for key, value in GUIDES.items()]}
    if topic not in GUIDES:
        raise Failure('INVALID_ARGUMENT', 'Unknown guide. Run small-cloud guide to list topics.')
    return {'topic': topic, 'content': GUIDES[topic][1]}
