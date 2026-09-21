import 'package:flutter/material.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../../auth/presentation/session_controller.dart';
import '../domain/onboarding_models.dart';

class OnboardingPage extends StatefulWidget {
  const OnboardingPage({super.key, required this.controller});

  final SessionController controller;

  @override
  State<OnboardingPage> createState() => _OnboardingPageState();
}

class _OnboardingPageState extends State<OnboardingPage> {
  static const _goals = <String, String>{
    'muscle_gain': '增肌',
    'fat_loss_retain': '减脂保肌',
    'recomposition': '增肌减脂',
    'maintain': '保持状态',
    'strength': '提升力量',
  };
  static const _trainingModes =
      <TrainingMode, ({String label, String description, IconData icon})>{
        TrainingMode.bodyweight: (
          label: '徒手训练',
          description: '不依赖健身器械，适合家中或户外训练',
          icon: Icons.accessibility_new_rounded,
        ),
        TrainingMode.gymEquipment: (
          label: '健身房器械训练',
          description: '使用哑铃、杠铃、绳索和深蹲架等器械',
          icon: Icons.fitness_center_rounded,
        ),
      };

  final _painBodyPart = TextEditingController();
  int _step = 0;
  String _goalType = 'muscle_gain';
  int _weeklyDays = 3;
  TrainingMode _trainingMode = TrainingMode.bodyweight;
  bool _hasPain = false;

  @override
  void dispose() {
    _painBodyPart.dispose();
    super.dispose();
  }

  bool get _canContinue => switch (_step) {
    0 || 1 || 2 => true,
    3 => !_hasPain || _painBodyPart.text.trim().isNotEmpty,
    _ => false,
  };

  Future<void> _continue() async {
    if (!_canContinue) return;
    if (_step < 3) {
      setState(() => _step += 1);
      return;
    }

    await widget.controller.completeOnboarding(
      OnboardingSubmission(
        goalType: _goalType,
        weeklyTrainingDays: _weeklyDays,
        equipment: _trainingMode.equipmentCodes,
        painBodyPart: _hasPain ? _painBodyPart.text.trim() : null,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      child: Scaffold(
        appBar: AppBar(
          title: const Row(
            children: [
              Icon(Icons.bolt_rounded, color: AppColors.primary),
              SizedBox(width: 8),
              Text('NxtRep'),
            ],
          ),
          actions: [
            TextButton(
              onPressed: widget.controller.submitting
                  ? null
                  : widget.controller.logout,
              child: const Text('退出'),
            ),
          ],
        ),
        body: SafeArea(
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 600),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(24, 16, 24, 24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    _StepProgress(current: _step),
                    const SizedBox(height: 12),
                    Text(
                      '第 ${_step + 1} 步，共 4 步',
                      style: Theme.of(context).textTheme.labelMedium,
                    ),
                    const SizedBox(height: 28),
                    Expanded(
                      child: SingleChildScrollView(child: _buildStep(context)),
                    ),
                    if (widget.controller.errorMessage case final message?) ...[
                      AppErrorCard(message: message),
                      const SizedBox(height: 12),
                    ],
                    Row(
                      children: [
                        if (_step > 0) ...[
                          OutlinedButton(
                            onPressed: widget.controller.submitting
                                ? null
                                : () => setState(() => _step -= 1),
                            child: const Text('上一步'),
                          ),
                          const SizedBox(width: 12),
                        ],
                        Expanded(
                          child: FilledButton(
                            onPressed:
                                widget.controller.submitting || !_canContinue
                                ? null
                                : _continue,
                            child: widget.controller.submitting
                                ? const SizedBox.square(
                                    dimension: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : Text(_step == 3 ? '保存并进入首页' : '继续'),
                          ),
                        ),
                      ],
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

  Widget _buildStep(BuildContext context) => switch (_step) {
    0 => _ChoiceStep(
      title: '你的首要目标是什么？',
      subtitle: '只选一个当前最重要的目标，之后可以修改。',
      children: _goals.entries
          .map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: _OptionCard(
                selected: _goalType == item.key,
                onTap: () => setState(() => _goalType = item.key),
                icon: _goalIcon(item.key),
                title: item.value,
              ),
            ),
          )
          .toList(),
    ),
    1 => _ChoiceStep(
      title: '每周准备训练几次？',
      subtitle: '先按现实可执行的频率来，计划会据此生成。',
      children: [
        Wrap(
          spacing: 10,
          runSpacing: 10,
          children: [
            for (var days = 1; days <= 7; days++)
              ChoiceChip(
                label: Text('$days 次'),
                selected: _weeklyDays == days,
                onSelected: (_) => setState(() => _weeklyDays = days),
              ),
          ],
        ),
      ],
    ),
    2 => _ChoiceStep(
      title: '你想用哪种方式训练？',
      subtitle: '只选一种常用训练环境，之后可以在个人资料中修改。',
      children: _trainingModes.entries
          .map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _OptionCard(
                selected: _trainingMode == item.key,
                onTap: () => setState(() => _trainingMode = item.key),
                icon: item.value.icon,
                title: item.value.label,
                subtitle: item.value.description,
              ),
            ),
          )
          .toList(),
    ),
    3 => _ChoiceStep(
      title: '目前有疼痛、旧伤或动作限制吗？',
      subtitle: '没有就选“没有”，不会上传空伤病记录。',
      children: [
        SegmentedButton<bool>(
          segments: const [
            ButtonSegment(value: false, label: Text('没有')),
            ButtonSegment(value: true, label: Text('有，需要避开')),
          ],
          selected: {_hasPain},
          onSelectionChanged: (value) {
            setState(() => _hasPain = value.single);
          },
        ),
        if (_hasPain) ...[
          const SizedBox(height: 20),
          TextField(
            controller: _painBodyPart,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: '疼痛或受限部位',
              hintText: '例如：右膝、下背部',
            ),
          ),
        ],
      ],
    ),
    _ => const SizedBox.shrink(),
  };
}

class _ChoiceStep extends StatelessWidget {
  const _ChoiceStep({
    required this.title,
    required this.subtitle,
    required this.children,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(title, style: Theme.of(context).textTheme.headlineLarge),
        const SizedBox(height: 8),
        Text(
          subtitle,
          style: Theme.of(context).textTheme.bodyLarge
              ?.copyWith(color: AppColors.muted),
        ),
        const SizedBox(height: 24),
        ...children,
      ],
    );
  }
}

class _StepProgress extends StatelessWidget {
  const _StepProgress({required this.current});

  final int current;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        for (var index = 0; index < 4; index++) ...[
          Expanded(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 220),
              height: 5,
              decoration: BoxDecoration(
                color: index <= current ? AppColors.primary : AppColors.line,
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
          if (index < 3) const SizedBox(width: 7),
        ],
      ],
    );
  }
}

class _OptionCard extends StatelessWidget {
  const _OptionCard({
    required this.selected,
    required this.onTap,
    required this.icon,
    required this.title,
    this.subtitle,
  });

  final bool selected;
  final VoidCallback onTap;
  final IconData icon;
  final String title;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      color: selected ? AppColors.primarySoft : AppColors.surface,
      borderColor: selected ? AppColors.primary : AppColors.line,
      padding: const EdgeInsets.symmetric(horizontal: 17, vertical: 16),
      child: Row(
        children: [
          Container(
            width: 46,
            height: 46,
            decoration: BoxDecoration(
              color: selected
                  ? AppColors.primary.withValues(alpha: 0.12)
                  : AppColors.indigoSoft,
              borderRadius: BorderRadius.circular(15),
            ),
            child: Icon(
              icon,
              color: selected ? AppColors.primary : AppColors.indigo,
            ),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.titleMedium),
                if (subtitle case final value?) ...[
                  const SizedBox(height: 4),
                  Text(
                    value,
                    style: Theme.of(context).textTheme.bodyMedium
                        ?.copyWith(color: AppColors.muted),
                  ),
                ],
              ],
            ),
          ),
          Icon(
            selected ? Icons.check_circle_rounded : Icons.circle_outlined,
            color: selected ? AppColors.primary : AppColors.muted,
          ),
        ],
      ),
    );
  }
}

IconData _goalIcon(String key) => switch (key) {
  'muscle_gain' => Icons.fitness_center_rounded,
  'fat_loss_retain' => Icons.local_fire_department_rounded,
  'recomposition' => Icons.sync_rounded,
  'maintain' => Icons.favorite_outline_rounded,
  'strength' => Icons.bolt_rounded,
  _ => Icons.flag_outlined,
};
