import 'package:flutter/material.dart';

import '../core/theme/app_theme.dart';
import '../features/auth/presentation/auth_gate.dart';
import '../features/auth/presentation/session_controller.dart';

class NxtRepApp extends StatefulWidget {
  const NxtRepApp({super.key, required this.sessionController, this.onDispose});

  final SessionController sessionController;
  final VoidCallback? onDispose;

  @override
  State<NxtRepApp> createState() => _NxtRepAppState();
}

class _NxtRepAppState extends State<NxtRepApp> {
  @override
  void initState() {
    super.initState();
    widget.sessionController.initialize();
  }

  @override
  void dispose() {
    widget.sessionController.dispose();
    widget.onDispose?.call();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'NxtRep',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      home: AuthGate(controller: widget.sessionController),
    );
  }
}
