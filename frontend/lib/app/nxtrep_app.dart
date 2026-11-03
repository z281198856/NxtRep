import 'package:flutter/material.dart';

import '../core/theme/app_theme.dart';
import '../core/offline/form_draft.dart';
import '../core/settings/app_preferences.dart';
import '../features/auth/presentation/auth_gate.dart';
import '../features/auth/presentation/session_controller.dart';

class NxtRepApp extends StatefulWidget {
  const NxtRepApp({super.key, required this.sessionController, this.onDispose});

  final SessionController sessionController;
  final VoidCallback? onDispose;

  @override
  State<NxtRepApp> createState() => _NxtRepAppState();
}

class _NxtRepAppState extends State<NxtRepApp> with WidgetsBindingObserver {
  final _navigatorKey = GlobalKey<NavigatorState>();
  bool _wasAuthenticated = false;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _wasAuthenticated =
        widget.sessionController.phase == SessionPhase.authenticated;
    widget.sessionController.addListener(_sessionChanged);
    widget.sessionController.initialize();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      widget.sessionController.systemReminders?.refresh();
    }
  }

  void _sessionChanged() {
    final phase = widget.sessionController.phase;
    if (_wasAuthenticated && phase == SessionPhase.signedOut) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          _navigatorKey.currentState?.popUntil((route) => route.isFirst);
        }
      });
    }
    _wasAuthenticated = phase == SessionPhase.authenticated;
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.sessionController.removeListener(_sessionChanged);
    widget.sessionController.dispose();
    widget.onDispose?.call();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: widget.sessionController,
      builder: (context, _) => LocalRecordsScope(
        records: widget.sessionController.localRecords,
        child: AppPreferencesScope(
          settings: widget.sessionController.appSettings,
          child: MaterialApp(
            navigatorKey: _navigatorKey,
            title: 'NxtRep',
            debugShowCheckedModeBanner: false,
            theme: AppTheme.light(),
            home: AuthGate(controller: widget.sessionController),
          ),
        ),
      ),
    );
  }
}
