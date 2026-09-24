import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/nutrition_models.dart';
import 'food_library_page.dart';
import 'nutrition_controller.dart';
import 'nutrition_tools_page.dart';
import 'widgets/food_line_art.dart';

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

  Future<void> _openFoods([String mealType = 'lunch']) async {
    final food = await Navigator.of(context).push<FoodItem>(
      MaterialPageRoute<FoodItem>(
        builder: (_) => FoodLibraryPage(controller: widget.controller),
      ),
    );
    if (food != null && mounted) await _recordFood(food, mealType);
  }

  Future<void> _recordFood(FoodItem food, [String mealType = 'lunch']) async {
    final input = await showModalBottomSheet<FoodServingInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _FoodServingSheet(food: food, mealType: mealType),
    );
    if (input == null) return;
    final saved = await widget.controller.addFood(input);
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text('已记录 ${food.name}')));
  }

  Future<void> _editEntry(NutritionEntry entry) async {
    final input = await showModalBottomSheet<NutritionEntryEditInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _NutritionEntryEditSheet(entry: entry),
    );
    if (input == null) return;
    final saved = await widget.controller.editEntry(entry, input);
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('饮食记录已更新')));
  }

  Future<void> _deleteEntry(NutritionEntry entry) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除这条饮食记录？'),
        content: Text('“${entry.displayName}”将从今日摄入中移除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认删除'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final deleted = await widget.controller.deleteEntry(entry);
    if (!mounted || !deleted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('饮食记录已删除')));
  }

  Future<void> _openTools() async {
    final food = await Navigator.of(context).push<FoodItem>(
      MaterialPageRoute<FoodItem>(
        builder: (_) => NutritionToolsPage(controller: widget.controller),
      ),
    );
    if (food != null && mounted) await _recordFood(food);
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
            tooltip: '饮食工具',
            onPressed: _openTools,
            icon: const Icon(Icons.auto_awesome_rounded),
          ),
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
        onPressed: widget.controller.submitting ? null : _openFoods,
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        icon: const Icon(Icons.add_rounded),
        label: const Text('添加食品'),
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
                const SizedBox(height: 20),
                AppSurface(
                  onTap: widget.controller.submitting ? null : _openFoods,
                  padding: const EdgeInsets.all(18),
                  child: Row(
                    children: [
                      const FoodLineArt(name: '鸡胸肉和米饭', size: 68),
                      const SizedBox(width: 16),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '浏览食品库',
                              style: Theme.of(context).textTheme.titleLarge,
                            ),
                            const SizedBox(height: 5),
                            Text(
                              '按蛋白质、主食、蔬菜和水果分类查找',
                              style: Theme.of(context).textTheme.bodyMedium
                                  ?.copyWith(color: AppColors.muted),
                            ),
                          ],
                        ),
                      ),
                      const Icon(
                        Icons.arrow_forward_rounded,
                        color: AppColors.primary,
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 24),
                SectionTitle(
                  title: '快速记录',
                  action: TextButton(
                    onPressed: widget.controller.submitting ? null : _add,
                    child: const Text('手动填写'),
                  ),
                ),
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
                        onTap: () => _openFoods('breakfast'),
                      ),
                      _MealShortcut(
                        icon: Icons.rice_bowl_rounded,
                        label: '午餐',
                        color: AppColors.indigo,
                        onTap: () => _openFoods('lunch'),
                      ),
                      _MealShortcut(
                        icon: Icons.dinner_dining_rounded,
                        label: '晚餐',
                        color: AppColors.primary,
                        onTap: () => _openFoods('dinner'),
                      ),
                      _MealShortcut(
                        icon: Icons.cookie_outlined,
                        label: '加餐',
                        color: AppColors.mint,
                        onTap: () => _openFoods('snack'),
                      ),
                    ],
                  ),
                ),
                if (widget.controller.frequentFoods.isNotEmpty) ...[
                  const SizedBox(height: 25),
                  const SectionTitle(title: '常用食品'),
                  const SizedBox(height: 11),
                  SizedBox(
                    height: 112,
                    child: ListView.separated(
                      scrollDirection: Axis.horizontal,
                      itemCount: widget.controller.frequentFoods.length,
                      separatorBuilder: (_, _) => const SizedBox(width: 10),
                      itemBuilder: (context, index) {
                        final item = widget.controller.frequentFoods[index];
                        return _FrequentFoodCard(
                          item: item,
                          onTap: () => _recordFood(item.food),
                        );
                      },
                    ),
                  ),
                ],
                if (widget.controller.weeklySummary case final weekly?) ...[
                  const SizedBox(height: 25),
                  const SectionTitle(title: '本周概览'),
                  const SizedBox(height: 11),
                  _WeeklySummaryCard(summary: weekly),
                ],
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
                  ...widget.controller.entries.map(
                    (entry) => _EntryTile(
                      entry,
                      onEdit: () => _editEntry(entry),
                      onDelete: () => _deleteEntry(entry),
                    ),
                  ),
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

class _FrequentFoodCard extends StatelessWidget {
  const _FrequentFoodCard({required this.item, required this.onTap});

  final FrequentFood item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 164,
      child: AppSurface(
        onTap: onTap,
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                FoodLineArt(
                  name: item.food.name,
                  brand: item.food.brand,
                  size: 34,
                ),
                const Spacer(),
                Text(
                  '${item.useCount} 次',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
            const Spacer(),
            Text(
              item.food.name,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 3),
            Text(
              '${item.food.kcal.toStringAsFixed(0)} kcal / '
              '${item.food.basisAmountG.toStringAsFixed(0)} g',
              style: Theme.of(context).textTheme.labelMedium,
            ),
          ],
        ),
      ),
    );
  }
}

class _WeeklySummaryCard extends StatelessWidget {
  const _WeeklySummaryCard({required this.summary});

  final WeeklyNutritionSummary summary;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      padding: const EdgeInsets.all(18),
      child: Column(
        children: [
          Row(
            children: [
              Expanded(
                child: _WeeklyMetric(
                  value: '${summary.recordedDays}/7',
                  label: '记录天数',
                ),
              ),
              Expanded(
                child: _WeeklyMetric(
                  value: '${summary.totalEntries}',
                  label: '总记录',
                ),
              ),
              Expanded(
                child: _WeeklyMetric(
                  value: summary.dailyAverage.kcal.toStringAsFixed(0),
                  label: '日均千卡',
                ),
              ),
            ],
          ),
          const SizedBox(height: 15),
          LinearProgressIndicator(
            value: summary.completeness.clamp(0.0, 1.0),
            minHeight: 7,
            borderRadius: BorderRadius.circular(999),
            color: AppColors.mint,
            backgroundColor: AppColors.mintSoft,
          ),
          const SizedBox(height: 7),
          Row(
            children: [
              Text(
                '记录完整度 ${(summary.completeness * 100).toStringAsFixed(0)}%',
                style: Theme.of(context).textTheme.labelMedium,
              ),
              const Spacer(),
              Text(
                '灵活餐 ${summary.flexibleMeals} 次',
                style: Theme.of(context).textTheme.labelMedium,
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _WeeklyMetric extends StatelessWidget {
  const _WeeklyMetric({required this.value, required this.label});

  final String value;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 3),
        Text(label, style: Theme.of(context).textTheme.labelMedium),
      ],
    );
  }
}

class _EntryTile extends StatelessWidget {
  const _EntryTile(this.entry, {required this.onEdit, required this.onDelete});

  final NutritionEntry entry;
  final VoidCallback onEdit;
  final VoidCallback onDelete;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: AppSurface(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            FoodLineArt(
              name: entry.items.isEmpty
                  ? entry.displayName
                  : entry.items.first.name,
              size: 45,
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
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: [
                Text(
                  '${entry.totals.kcal.toStringAsFixed(0)} kcal',
                  style: Theme.of(context).textTheme.labelLarge,
                ),
                if (entry.isFlexibleMeal)
                  const Text(
                    '灵活餐',
                    style: TextStyle(color: AppColors.amber, fontSize: 12),
                  ),
              ],
            ),
            PopupMenuButton<String>(
              tooltip: '更多操作',
              onSelected: (value) {
                if (value == 'edit') onEdit();
                if (value == 'delete') onDelete();
              },
              itemBuilder: (_) => const [
                PopupMenuItem(value: 'edit', child: Text('编辑')),
                PopupMenuItem(value: 'delete', child: Text('删除')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _FoodServingSheet extends StatefulWidget {
  const _FoodServingSheet({required this.food, required this.mealType});

  final FoodItem food;
  final String mealType;

  @override
  State<_FoodServingSheet> createState() => _FoodServingSheetState();
}

class _FoodServingSheetState extends State<_FoodServingSheet> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _amount;
  final _notes = TextEditingController();
  late String _mealType;
  bool _flexible = false;

  @override
  void initState() {
    super.initState();
    _amount = TextEditingController(
      text: widget.food.basisAmountG.toStringAsFixed(0),
    );
    _mealType = widget.mealType;
    _amount.addListener(_refreshPreview);
  }

  void _refreshPreview() => setState(() {});

  @override
  void dispose() {
    _amount
      ..removeListener(_refreshPreview)
      ..dispose();
    _notes.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.pop(
      context,
      FoodServingInput(
        food: widget.food,
        amountG: double.parse(_amount.text),
        mealType: _mealType,
        isFlexibleMeal: _flexible,
        notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final amount = double.tryParse(_amount.text) ?? 0;
    final ratio = widget.food.basisAmountG <= 0
        ? 0
        : amount / widget.food.basisAmountG;
    return SafeArea(
      top: false,
      child: Padding(
        padding: EdgeInsets.only(
          left: 20,
          top: 8,
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
                Row(
                  children: [
                    FoodLineArt(
                      name: widget.food.name,
                      brand: widget.food.brand,
                      size: 62,
                    ),
                    const SizedBox(width: 13),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            widget.food.name,
                            style: Theme.of(context).textTheme.headlineSmall,
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '基准 ${widget.food.basisAmountG.toStringAsFixed(0)} g · '
                            '${widget.food.kcal.toStringAsFixed(0)} kcal',
                            style: Theme.of(context).textTheme.bodyMedium
                                ?.copyWith(color: AppColors.muted),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 18),
                DropdownButtonFormField<String>(
                  initialValue: _mealType,
                  decoration: const InputDecoration(labelText: '餐次'),
                  items: _mealItems,
                  onChanged: (value) => _mealType = value!,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _amount,
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(
                      RegExp(r'^\d*\.?\d{0,3}'),
                    ),
                  ],
                  decoration: const InputDecoration(labelText: '实际份量（g）'),
                  validator: (value) {
                    final parsed = double.tryParse(value ?? '');
                    return parsed == null || parsed <= 0 ? '请输入有效份量' : null;
                  },
                ),
                const SizedBox(height: 12),
                AppSurface(
                  color: AppColors.mintSoft,
                  borderColor: AppColors.mintSoft,
                  padding: const EdgeInsets.all(14),
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceAround,
                    children: [
                      _NutritionPreview(
                        label: '热量',
                        value:
                            '${(widget.food.kcal * ratio).toStringAsFixed(0)} kcal',
                      ),
                      _NutritionPreview(
                        label: '蛋白质',
                        value:
                            '${(widget.food.proteinG * ratio).toStringAsFixed(1)} g',
                      ),
                      _NutritionPreview(
                        label: '碳水',
                        value:
                            '${(widget.food.carbsG * ratio).toStringAsFixed(1)} g',
                      ),
                      _NutritionPreview(
                        label: '脂肪',
                        value:
                            '${(widget.food.fatG * ratio).toStringAsFixed(1)} g',
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('标记为灵活餐'),
                  subtitle: const Text('用于聚餐、外食等不要求精确控制的餐次'),
                  value: _flexible,
                  onChanged: (value) => setState(() => _flexible = value),
                ),
                TextFormField(
                  controller: _notes,
                  maxLines: 2,
                  decoration: const InputDecoration(labelText: '备注（可选）'),
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
}

class _NutritionPreview extends StatelessWidget {
  const _NutritionPreview({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(value, style: Theme.of(context).textTheme.labelLarge),
        const SizedBox(height: 2),
        Text(label, style: Theme.of(context).textTheme.labelMedium),
      ],
    );
  }
}

class _NutritionEntryEditSheet extends StatefulWidget {
  const _NutritionEntryEditSheet({required this.entry});

  final NutritionEntry entry;

  @override
  State<_NutritionEntryEditSheet> createState() =>
      _NutritionEntryEditSheetState();
}

class _NutritionEntryEditSheetState extends State<_NutritionEntryEditSheet> {
  final _formKey = GlobalKey<FormState>();
  late final List<TextEditingController> _amounts;
  late final TextEditingController _notes;
  late String _mealType;
  late bool _flexible;

  @override
  void initState() {
    super.initState();
    _mealType = widget.entry.mealType;
    _flexible = widget.entry.isFlexibleMeal;
    _notes = TextEditingController(text: widget.entry.notes);
    _amounts = widget.entry.items
        .map(
          (item) =>
              TextEditingController(text: item.amountG.toStringAsFixed(1)),
        )
        .toList(growable: false);
  }

  @override
  void dispose() {
    for (final controller in _amounts) {
      controller.dispose();
    }
    _notes.dispose();
    super.dispose();
  }

  void _submit() {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    Navigator.pop(
      context,
      NutritionEntryEditInput(
        mealType: _mealType,
        items: [
          for (var index = 0; index < widget.entry.items.length; index++)
            widget.entry.items[index].withAmount(
              double.parse(_amounts[index].text),
            ),
        ],
        isFlexibleMeal: _flexible,
        notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
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
          top: 8,
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
                Text(
                  '编辑饮食记录',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 18),
                DropdownButtonFormField<String>(
                  initialValue: _mealType,
                  decoration: const InputDecoration(labelText: '餐次'),
                  items: _mealItems,
                  onChanged: (value) => _mealType = value!,
                ),
                const SizedBox(height: 12),
                for (
                  var index = 0;
                  index < widget.entry.items.length;
                  index++
                ) ...[
                  TextFormField(
                    controller: _amounts[index],
                    keyboardType: const TextInputType.numberWithOptions(
                      decimal: true,
                    ),
                    inputFormatters: [
                      FilteringTextInputFormatter.allow(
                        RegExp(r'^\d*\.?\d{0,3}'),
                      ),
                    ],
                    decoration: InputDecoration(
                      labelText: '${widget.entry.items[index].name} 份量（g）',
                    ),
                    validator: (value) {
                      final parsed = double.tryParse(value ?? '');
                      return parsed == null || parsed <= 0 ? '请输入有效份量' : null;
                    },
                  ),
                  const SizedBox(height: 12),
                ],
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('标记为灵活餐'),
                  value: _flexible,
                  onChanged: (value) => setState(() => _flexible = value),
                ),
                TextFormField(
                  controller: _notes,
                  maxLines: 2,
                  decoration: const InputDecoration(labelText: '备注（可选）'),
                ),
                const SizedBox(height: 18),
                FilledButton(onPressed: _submit, child: const Text('保存修改')),
              ],
            ),
          ),
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
  final _notes = TextEditingController();
  late String _mealType;
  bool _flexible = false;

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
    _notes.dispose();
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
        isFlexibleMeal: _flexible,
        notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
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
                  items: _mealItems,
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
                SwitchListTile.adaptive(
                  contentPadding: EdgeInsets.zero,
                  title: const Text('标记为灵活餐'),
                  value: _flexible,
                  onChanged: (value) => setState(() => _flexible = value),
                ),
                TextFormField(
                  controller: _notes,
                  maxLines: 2,
                  decoration: const InputDecoration(labelText: '备注（可选）'),
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

const _mealItems = <DropdownMenuItem<String>>[
  DropdownMenuItem(value: 'breakfast', child: Text('早餐')),
  DropdownMenuItem(value: 'lunch', child: Text('午餐')),
  DropdownMenuItem(value: 'dinner', child: Text('晚餐')),
  DropdownMenuItem(value: 'snack', child: Text('加餐')),
  DropdownMenuItem(value: 'other', child: Text('其他')),
];
