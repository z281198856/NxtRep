import 'dart:math';

import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';

class AppLoadingPage extends StatefulWidget {
  const AppLoadingPage({super.key});

  @override
  State<AppLoadingPage> createState() => _AppLoadingPageState();
}

class _AppLoadingPageState extends State<AppLoadingPage> {
  static const _quotes = [
    '每一次坚持，都在靠近更好的自己。',
    '不必一步到位，只要今天向前一步。',
    '进步来自积累，而不是一时用力。',
    '照顾好身体，也给自己一点耐心。',
    '训练有节奏，进步有回响。',
    '认真吃饭，好好休息，稳稳变强。',
    '比昨天多一点努力，比焦虑多一点耐心。',
    '让行动成为习惯，让改变慢慢发生。',
    '今天的一小步，是明天的底气。',
    '按自己的节奏，走向想成为的自己。',
  ];

  // Choose once per loading screen, not on every rebuild or animation frame.
  late final String _quote = _quotes[Random().nextInt(_quotes.length)];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 360),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    'NxtRep',
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.displaySmall
                        ?.copyWith(fontSize: 46, letterSpacing: -1.5),
                  ),
                  const SizedBox(height: 22),
                  Text(
                    _quote,
                    textAlign: TextAlign.center,
                    style: Theme.of(context).textTheme.bodyLarge
                        ?.copyWith(color: AppColors.muted, height: 1.7),
                  ),
                  const SizedBox(height: 32),
                  const SizedBox(
                    width: 64,
                    child: LinearProgressIndicator(
                      minHeight: 3,
                      borderRadius: BorderRadius.all(Radius.circular(2)),
                      backgroundColor: AppColors.primarySoft,
                      semanticsLabel: '正在加载',
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
