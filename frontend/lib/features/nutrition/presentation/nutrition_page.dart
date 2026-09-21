import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/nutrition_models.dart';
import 'nutrition_controller.dart';

class NutritionPage extends StatefulWidget {
  const NutritionPage({super.key, required this.controller});

  final NutritionController controller;

  @override
  State<NutritionPage> createState() => _NutritionPageState();
}

class _NutritionPageState extends State<NutritionPage> {
  @override
  void initState() {
    super.initState();
    widget.controller.refresh();
  }

  Future<void> _add([String mealType = 'lunch']) async {
    final input = await showModalBottomSheet<ManualNutritionInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _NutritionEntrySheet(initialMealType: mealType),
    );
    if (input != null) {
      await widget.controller.add(input);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          tooltip: '返回',
          onPressed: () => Navigator.maybePop(context),
          icon: const Icon(Icons.arrow_back_rounded),
        ),
        title: const Text('饮食记录'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: widget.controller.loading
                ? null
                : widget.controller.refresh,
            icon: const Icon(Icons.refresh_rounded),
          ),
          const SizedBox(width: 8),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: widget.controller.submitting ? null : _add,
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_rounded),
        label: const Text('记录饮食'),
      ),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) {
          final summary = widget.controller.summary;
          return RefreshIndicator(
            onRefresh: widget.controller.refresh,
            child: ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 108),
              children: [
                if (widget.controller.loading && summary == null)
                  const AppSurface(
                    child: Center(
                      child: Padding(
                        padding: EdgeInsets.all(30),
                        child: CircularProgressIndicator(),
                      ),
                    ),
                  ),
                if (summary != null) _SummaryCard(summary: summary),
                if (widget.controller.errorMessage case final message?) ...[
                  const SizedBox(height: 12),
                  AppErrorCard(message: message),
                ],
                const SizedBox(height: 24),
                const SectionTitle(title: '快速记录'),
                const SizedBox(height: 11),
                AppSurface(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 8,
                    vertical: 14,
                  ),
                  child: Row(
                    children: [
                      _MealShortcut(
                        icon: Icons.free_breakfast_rounded,
                        label: '早餐',
                        color: AppColors.amber,
                        onTap: () => _add('breakfast'),
                      ),
                      _MealShortcut(
                        icon: Icons.rice_bowl_rounded,
                        label: '午餐',
                        color: AppColors.indigo,
                        onTap: () => _add('lunch'),
                      ),
                      _MealShortcut(
                        icon: Icons.dinner_dining_rounded,
                        label: '晚餐',
                        color: AppColors.primary,
                        onTap: () => _add('dinner'),
                      ),
                      _MealShortcut(
                        icon: Icons.cookie_outlined,
                        label: '加餐',
                        color: AppColors.mint,
                        onTap: () => _add('snack'),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 25),
                const SectionTitle(title: '今日记录'),
                const SizedBox(height: 11),
                if (!widget.controller.loading &&
                    widget.controller.entries.isEmpty)
                  const AppEmptyState(
                    icon: Icons.restaurant_menu_rounded,
                    title: '今天还没有饮食记录',
                    message: '从早餐、午餐、晚餐或加餐中选择一项开始记录。',
                  )
                else
                  ...widget.controller.entries.map(_EntryTile.new),
              ],
            ),
          );
        },
      ),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.summary});

  final DailyNutritionSummary summary;

  @override
  Widget build(BuildContext context) {
    final targetKcal = _number(summary.target?['kcal']);
    return AppSurface(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Text(
                summary.consumed.kcal.toStringAsFixed(0),
                style: Theme.of(context).textTheme.displaySmall,
              ),
              const SizedBox(width: 6),
              Padding(
                padding: const EdgeInsets.only(bottom: 4),
                child: Text(
                  targetKcal > 0
                      ? '/ ${targetKcal.toStringAsFixed(0)} 千卡'
                      : '千卡',
                  style: Theme.of(context).textTheme.bodyLarge
                      ?.copyWith(color: AppColors.muted),
                ),
              ),
              const Spacer(),
              StatusPill(
                label:
                    '${(summary.completeness * 100).clamp(0, 100).toStringAsFixed(0)}% 完整',
                color: AppColors.mint,
                icon: Icons.check_circle_outline_rounded,
              ),
            ],
          ),
          const SizedBox(height: 7),
          Text(
            '今日摄入',
            style: Theme.of(context).textTheme.bodyMedium
                ?.copyWith(color: AppColors.muted),
          ),
          const SizedBox(height: 22),
          Row(
            children: [
              Expanded(
                child: _MacroRing(
                  label: '蛋白质',
                  value: summary.consumed.proteinG,
                  target: _number(summary.target?['protein_g']),
                  color: AppColors.amber,
                ),
              ),
              Expanded(
                child: _MacroRing(
                  label: '碳水',
                  value: summary.consumed.carbsG,
                  target: _number(summary.target?['carbs_g']),
                  color: AppColors.indigo,
                ),
              ),
              Expanded(
                child: _MacroRing(
                  label: '脂肪',
                  value: summary.consumed.fatG,
                  target: _number(summary.target?['fat_g']),
                  color: AppColors.primary,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MacroRing extends StatelessWidget {
  const _MacroRing({
    required this.label,
    required this.value,
    required this.target,
    required this.color,
  });

  final String label;
  final double value;
  final double target;
  final Color color;

  @override
  Widget build(BuildContext context) {
    final progress = target <= 0 ? 0.0 : (value / target).clamp(0.0, 1.0);
    return Semantics(
      label:
          '$label ${value.toStringAsFixed(0)}克${target > 0 ? '，目标${target.toStringAsFixed(0)}克' : ''}',
      child: Column(
        children: [
          SizedBox.square(
            dimension: 72,
            child: Stack(
              alignment: Alignment.center,
              children: [
                CircularProgressIndicator(
                  value: 1,
                  strokeWidth: 7,
                  color: color.withValues(alpha: 0.12),
                ),
                CircularProgressIndicator(
                  value: progress,
                  strokeWidth: 7,
                  strokeCap: StrokeCap.round,
                  color: color,
                ),
                Text(
                  value.toStringAsFixed(0),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ],
            ),
          ),
          const SizedBox(height: 9),
          Text(label, style: Theme.of(context).textTheme.labelLarge),
          const SizedBox(height: 2),
          Text(
            target > 0 ? '/ ${target.toStringAsFixed(0)} g' : '目标 --',
            style: Theme.of(context).textTheme.labelMedium,
          ),
        ],
      ),
    );
  }
}

class _MealShortcut extends StatelessWidget {
  const _MealShortcut({
    required this.icon,
    required this.label,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 5),
          child: Column(
            children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: color.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: color, size: 22),
              ),
              const SizedBox(height: 7),
              Text(label, style: Theme.of(context).textTheme.labelMedium),
            ],
          ),
        ),
      ),
    );
  }
}

class _EntryTile extends StatelessWidget {
  const _EntryTile(this.entry);

  final NutritionEntry entry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppSurface(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Container(
              width: 43,
              height: 43,
              decoration: BoxDecoration(
                color: AppColors.amberSoft,
                borderRadius: BorderRadius.circular(14),
              ),
              child: const Icon(
                Icons.restaurant_rounded,
                color: AppColors.amber,
              ),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    entry.displayName,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 3),
                  Text(
                    _mealLabel(entry.mealType),
                    style: Theme.of(context).textTheme.labelMedium,
                  ),
                ],
              ),
            ),
            Text(
              '${entry.totals.kcal.toStringAsFixed(0)} kcal',
              style: Theme.of(context).textTheme.labelLarge,
            ),
          ],
        ),
      ),
    );
  }
}

class _NutritionEntrySheet extends StatefulWidget {
  const _NutritionEntrySheet({required this.initialMealType});

  final String initialMealType;

  @override
  State<_NutritionEntrySheet> createState() => _NutritionEntrySheetState();
}

class _NutritionEntrySheetState extends State<_NutritionEntrySheet> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _amount = TextEditingController(text: '100');
  final _kcal = TextEditingController();
  final _protein = TextEditingController(text: '0');
  final _carbs = TextEditingController(text: '0');
  final _fat = TextEditingController(text: '0');
  late String _mealType;

  @override
  void initState() {
    super.initState();
    _mealType = widget.initialMealType;
  }

  @override
  void dispose() {
    _name.dispose();
    _amount.dispose();
    _kcal.dispose();
    _protein.dispose();
    _carbs.dispose();
    _fat.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.pop(
      context,
      ManualNutritionInput(
        name: _name.text.trim(),
        mealType: _mealType,
        amountG: double.parse(_amount.text),
        kcal: double.parse(_kcal.text),
        proteinG: double.parse(_protein.text),
        carbsG: double.parse(_carbs.text),
        fatG: double.parse(_fat.text),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.only(
          left: 20,
          top: 4,
          right: 20,
          bottom: MediaQuery.viewInsetsOf(context).bottom + 20,
        ),
        child: Form(
          key: _formKey,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('记录饮食', style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 6),
                Text(
                  '先快速记录，后续可以继续补充更精确的数据。',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
                const SizedBox(height: 20),
                DropdownButtonFormField<String>(
                  initialValue: _mealType,
                  decoration: const InputDecoration(labelText: '餐次'),
                  items: const [
                    DropdownMenuItem(value: 'breakfast', child: Text('早餐')),
                    DropdownMenuItem(value: 'lunch', child: Text('午餐')),
                    DropdownMenuItem(value: 'dinner', child: Text('晚餐')),
                    DropdownMenuItem(value: 'snack', child: Text('加餐')),
                    DropdownMenuItem(value: 'other', child: Text('其他')),
                  ],
                  onChanged: (value) => _mealType = value!,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: '食物名称'),
                  validator: (value) =>
                      (value?.trim().isEmpty ?? true) ? '请输入名称' : null,
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: _numberField(_amount, '份量（g）', positive: true),
                    ),
                    const SizedBox(width: 10),
                    Expanded(child: _numberField(_kcal, '热量（kcal）')),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(child: _numberField(_protein, '蛋白质（g）')),
                    const SizedBox(width: 8),
                    Expanded(child: _numberField(_carbs, '碳水（g）')),
                    const SizedBox(width: 8),
                    Expanded(child: _numberField(_fat, '脂肪（g）')),
                  ],
                ),
                const SizedBox(height: 18),
                FilledButton(onPressed: _submit, child: const Text('保存记录')),
              ],
            ),
          ),
        ),
      ),
    );
  }

  TextFormField _numberField(
    TextEditingController controller,
    String label, {
    bool positive = false,
  }) {
    return TextFormField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: [
        FilteringTextInputFormatter.allow(RegExp(r'^\d*\.?\d{0,3}')),
      ],
      decoration: InputDecoration(labelText: label),
      validator: (value) {
        final parsed = double.tryParse(value ?? '');
        if (parsed == null || parsed < 0 || (positive && parsed == 0)) {
          return '无效';
        }
        return null;
      },
    );
  }
}

double _number(Object? value) => switch (value) {
  num number => number.toDouble(),
  String text => double.tryParse(text) ?? 0,
  _ => 0,
};

String _mealLabel(String value) => switch (value) {
  'breakfast' => '早餐',
  'lunch' => '午餐',
  'dinner' => '晚餐',
  'snack' => '加餐',
  _ => '其他',
};
