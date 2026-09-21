import 'package:flutter/material.dart';

import 'session_controller.dart';

class PasswordSetupPage extends StatefulWidget {
  const PasswordSetupPage({
    super.key,
    required this.controller,
    this.initialUsername,
  });

  final SessionController controller;
  final String? initialUsername;

  @override
  State<PasswordSetupPage> createState() => _PasswordSetupPageState();
}

class _PasswordSetupPageState extends State<PasswordSetupPage> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _username;
  final _setupToken = TextEditingController();
  final _password = TextEditingController();
  final _confirmPassword = TextEditingController();
  bool _obscure = true;

  @override
  void initState() {
    super.initState();
    _username = TextEditingController(text: widget.initialUsername);
  }

  @override
  void dispose() {
    _username.dispose();
    _setupToken.dispose();
    _password.dispose();
    _confirmPassword.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    await widget.controller.setupPassword(
      username: _username.text,
      setupToken: _setupToken.text,
      newPassword: _password.text,
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          onPressed: widget.controller.submitting
              ? null
              : widget.controller.showLogin,
          icon: const Icon(Icons.arrow_back_rounded),
        ),
        title: const Text('首次设置密码'),
      ),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      '使用管理员提供的一次性设置令牌创建密码。',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const SizedBox(height: 24),
                    if (widget.controller.errorMessage case final message?) ...[
                      Text(
                        message,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    TextFormField(
                      controller: _username,
                      decoration: const InputDecoration(labelText: '用户名'),
                      validator: (value) =>
                          (value?.trim().isEmpty ?? true) ? '请输入用户名' : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _setupToken,
                      autocorrect: false,
                      decoration: const InputDecoration(labelText: '设置令牌'),
                      validator: (value) =>
                          (value?.trim().isEmpty ?? true) ? '请输入设置令牌' : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _password,
                      obscureText: _obscure,
                      decoration: InputDecoration(
                        labelText: '新密码（至少 8 位）',
                        suffixIcon: IconButton(
                          onPressed: () => setState(() => _obscure = !_obscure),
                          icon: Icon(
                            _obscure
                                ? Icons.visibility_outlined
                                : Icons.visibility_off_outlined,
                          ),
                        ),
                      ),
                      validator: (value) =>
                          (value?.length ?? 0) < 8 ? '密码至少需要 8 位' : null,
                    ),
                    const SizedBox(height: 14),
                    TextFormField(
                      controller: _confirmPassword,
                      obscureText: _obscure,
                      onFieldSubmitted: (_) => _submit(),
                      decoration: const InputDecoration(labelText: '确认新密码'),
                      validator: (value) =>
                          value != _password.text ? '两次输入的密码不一致' : null,
                    ),
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: widget.controller.submitting ? null : _submit,
                      child: const Text('设置并继续'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
