import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/auth_models.dart';
import 'account_security_controller.dart';

class AccountSecurityPage extends StatefulWidget {
  const AccountSecurityPage({super.key, required this.controller});
  final AccountSecurityController controller;

  @override
  State<AccountSecurityPage> createState() => _AccountSecurityPageState();
}

class _AccountSecurityPageState extends State<AccountSecurityPage> {
  AccountSecurityController get controller => widget.controller;
  @override
  void initState() {
    super.initState();
    controller.refresh();
  }

  Future<void> _changePassword() async {
    controller.clearError();
    final changed = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ChangePasswordPage(controller: controller),
      ),
    );
    if (mounted && changed == true) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('密码已修改，当前设备保持登录，其他登录已退出')));
    }
  }

  Future<void> _revoke([AccountSession? session]) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(session == null ? '退出其他设备？' : '退出这台设备？'),
        content: Text(
          session == null
              ? '当前设备保持登录，其他登录需要重新验证密码。'
              : '将退出“${session.deviceName ?? '未命名设备'}”的这次登录，当前设备不受影响。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认退出'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    final saved = await controller.revoke(session);
    if (mounted && saved) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(session == null ? '其他设备已退出' : '该设备已退出')),
      );
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('账户安全')),
    body: ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final sessions = [...controller.sessions]
          ..sort(
            (a, b) => a.isCurrent == b.isCurrent
                ? b.createdAt.compareTo(a.createdAt)
                : a.isCurrent
                ? -1
                : 1,
          );
        return RefreshIndicator(
          onRefresh: controller.refresh,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
            children: [
              AppSurface(
                padding: EdgeInsets.zero,
                child: ListTile(
                  leading: const Icon(
                    Icons.password_rounded,
                    color: AppColors.indigo,
                  ),
                  title: const Text('修改密码'),
                  subtitle: const Text('修改后保留本机，退出其他登录'),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  enabled: !controller.busy,
                  onTap: _changePassword,
                ),
              ),
              const SizedBox(height: 26),
              SectionTitle(
                title: '登录设备',
                action: TextButton.icon(
                  onPressed: controller.busy ? null : controller.refresh,
                  icon: const Icon(Icons.refresh_rounded, size: 19),
                  label: const Text('刷新'),
                ),
              ),
              const SizedBox(height: 8),
              const Text('已标记当前设备；同一设备多次登录可能显示多条。'),
              const SizedBox(height: 14),
              if (controller.loading) const LinearProgressIndicator(),
              if (controller.errorMessage case final message?) ...[
                AppErrorCard(message: message),
                const SizedBox(height: 12),
              ],
              for (final session in sessions)
                Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: AppSurface(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            const Icon(
                              Icons.devices_rounded,
                              color: AppColors.indigo,
                            ),
                            const SizedBox(width: 12),
                            Expanded(
                              child: Text(
                                session.deviceName?.trim().isNotEmpty == true
                                    ? session.deviceName!
                                    : '未命名设备',
                                style: Theme.of(context).textTheme.titleMedium,
                              ),
                            ),
                            if (session.isCurrent)
                              const StatusPill(
                                label: '当前设备',
                                color: AppColors.indigo,
                              ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        Text('首次登录：${_time(session.createdAt)}'),
                        Text(
                          '最近使用：${_time(session.lastUsedAt ?? session.createdAt)}',
                        ),
                        if (!session.isCurrent)
                          Align(
                            alignment: Alignment.centerRight,
                            child: TextButton.icon(
                              key: ValueKey('revoke-${session.id}'),
                              onPressed: controller.busy
                                  ? null
                                  : () => _revoke(session),
                              icon: const Icon(Icons.logout_rounded, size: 18),
                              label: const Text('退出该设备'),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              if (controller.otherCount > 0) ...[
                const SizedBox(height: 6),
                OutlinedButton.icon(
                  onPressed: controller.busy ? null : () => _revoke(),
                  icon: const Icon(Icons.phonelink_erase_rounded),
                  label: const Text('退出其他所有设备'),
                ),
              ],
              if (!controller.loading &&
                  sessions.isNotEmpty &&
                  controller.otherCount == 0)
                const Text('目前只有当前设备保持登录。'),
            ],
          ),
        );
      },
    ),
  );

  String _time(DateTime value) {
    final date = value.toLocal();
    String pad(int value) => value.toString().padLeft(2, '0');
    return '${date.year}-${pad(date.month)}-${pad(date.day)} ${pad(date.hour)}:${pad(date.minute)}';
  }
}

class ChangePasswordPage extends StatefulWidget {
  const ChangePasswordPage({super.key, required this.controller});
  final AccountSecurityController controller;
  @override
  State<ChangePasswordPage> createState() => _ChangePasswordPageState();
}

class _ChangePasswordPageState extends State<ChangePasswordPage> {
  final _form = GlobalKey<FormState>();
  final _current = TextEditingController();
  final _next = TextEditingController();
  final _repeat = TextEditingController();
  final _visible = <String>{};

  @override
  void dispose() {
    _current.dispose();
    _next.dispose();
    _repeat.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_form.currentState?.validate() ?? false)) return;
    FocusScope.of(context).unfocus();
    final saved = await widget.controller.changePassword(
      _current.text,
      _next.text,
    );
    if (!mounted) return;
    if (saved) {
      TextInput.finishAutofillContext(shouldSave: true);
      _current.clear();
      _next.clear();
      _repeat.clear();
      Navigator.pop(context, true);
    } else if (widget.controller.errorCode == 'INVALID_CURRENT_PASSWORD') {
      _current.clear();
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller,
    builder: (context, _) => PopScope(
      canPop: !widget.controller.changingPassword,
      child: Scaffold(
        appBar: AppBar(title: const Text('修改密码')),
        body: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          child: AutofillGroup(
            child: Form(
              key: _form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text('新密码需为 8–128 个字符，且与当前密码不同。修改成功后，其他登录设备将退出。'),
                  const SizedBox(height: 22),
                  _field(
                    'current',
                    '当前密码',
                    _current,
                    (value) => value == null || value.isEmpty
                        ? '请输入当前密码'
                        : value.length > 128
                        ? '密码不能超过 128 个字符'
                        : null,
                  ),
                  const SizedBox(height: 16),
                  _field(
                    'next',
                    '新密码',
                    _next,
                    (value) =>
                        value == null || value.length < 8 || value.length > 128
                        ? '请输入 8–128 个字符的新密码'
                        : value == _current.text
                        ? '新密码不能与当前密码相同'
                        : null,
                  ),
                  const SizedBox(height: 16),
                  _field(
                    'repeat',
                    '确认新密码',
                    _repeat,
                    (value) => value == null || value.isEmpty
                        ? '请再次输入新密码'
                        : value != _next.text
                        ? '两次输入的新密码不一致'
                        : null,
                  ),
                  if (widget.controller.errorMessage case final message?) ...[
                    const SizedBox(height: 16),
                    AppErrorCard(message: message),
                  ],
                  const SizedBox(height: 24),
                  FilledButton(
                    onPressed: widget.controller.busy ? null : _submit,
                    child: widget.controller.changingPassword
                        ? const SizedBox(
                            height: 20,
                            width: 20,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('确认修改密码'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    ),
  );

  Widget _field(
    String key,
    String label,
    TextEditingController controller,
    String? Function(String?) validator,
  ) => TextFormField(
    key: ValueKey('password-$key'),
    controller: controller,
    enabled: !widget.controller.changingPassword,
    obscureText: !_visible.contains(key),
    autocorrect: false,
    enableSuggestions: false,
    autofillHints: [
      key == 'current' ? AutofillHints.password : AutofillHints.newPassword,
    ],
    textInputAction: key == 'repeat'
        ? TextInputAction.done
        : TextInputAction.next,
    onFieldSubmitted: key == 'repeat' ? (_) => _submit() : null,
    validator: validator,
    decoration: InputDecoration(
      labelText: label,
      suffixIcon: IconButton(
        tooltip: _visible.contains(key) ? '隐藏密码' : '显示密码',
        onPressed: () => setState(() {
          if (!_visible.add(key)) _visible.remove(key);
        }),
        icon: Icon(
          _visible.contains(key)
              ? Icons.visibility_off_outlined
              : Icons.visibility_outlined,
        ),
      ),
    ),
  );
}
