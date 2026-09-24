import 'package:flutter/material.dart';

import '../../../core/widgets/app_widgets.dart';
import '../domain/nutrition_models.dart';
import 'nutrition_controller.dart';

class NutritionToolsPage extends StatefulWidget {
  const NutritionToolsPage({super.key, required this.controller});

  final NutritionController controller;

  @override
  State<NutritionToolsPage> createState() => _NutritionToolsPageState();
}

class _NutritionToolsPageState extends State<NutritionToolsPage> {
  final _mealText = TextEditingController();
  final _barcode = TextEditingController();
  final _adviceFood = TextEditingController();
  String _mealType = 'lunch';
  NutritionTextDraft? _draft;
  FoodItem? _barcodeFood;
  NutritionAdvice? _advice;
  List<FlexibleMeal> _flexibleMeals = const [];
  List<RecipeSummary> _recipes = const [];

  @override
  void initState() {
    super.initState();
    _refreshLists();
  }

  @override
  void dispose() {
    _mealText.dispose();
    _barcode.dispose();
    _adviceFood.dispose();
    super.dispose();
  }

  Future<void> _refreshLists() async {
    final flexibleMeals = await widget.controller.listFlexibleMeals();
    final recipes = await widget.controller.listRecipes();
    if (!mounted) return;
    setState(() {
      _flexibleMeals = flexibleMeals;
      _recipes = recipes;
    });
  }

  Future<void> _createRecipe() async {
    final food = _barcodeFood;
    if (food == null) return;
    final input = await showDialog<(String, double)>(
      context: context,
      builder: (_) => _RecipeEditorDialog(
        initialName: '${food.name}食谱',
        initialAmountG: food.basisAmountG,
      ),
    );
    if (input == null || input.$1.isEmpty || input.$2 <= 0) return;
    final saved = await widget.controller.createRecipe(
      name: input.$1,
      servings: 1,
      food: food,
      amountG: input.$2,
    );
    if (saved != null) await _refreshLists();
  }

  Future<void> _parseMeal() async {
    final draft = await widget.controller.parseTextDraft(
      text: _mealText.text,
      mealType: _mealType,
    );
    if (mounted) setState(() => _draft = draft);
  }

  Future<void> _saveDraft() async {
    final draft = _draft;
    if (draft == null) return;
    final saved = await widget.controller.submitTextDraft(draft);
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('智能识别的饮食已记录')));
    setState(() {
      _draft = null;
      _mealText.clear();
    });
  }

  Future<void> _lookupBarcode() async {
    final food = await widget.controller.lookupBarcode(_barcode.text);
    if (mounted) setState(() => _barcodeFood = food);
  }

  Future<void> _getAdvice() async {
    final advice = await widget.controller.getAdvice(_adviceFood.text);
    if (mounted) setState(() => _advice = advice);
  }

  Future<void> _scheduleFlexibleMeal() async {
    final date = await showDatePicker(
      context: context,
      initialDate: DateTime.now().add(const Duration(days: 1)),
      firstDate: DateTime.now(),
      lastDate: DateTime.now().add(const Duration(days: 180)),
    );
    if (date == null) return;
    if (!mounted) return;
    final label = await showDialog<String>(
      context: context,
      builder: (_) => const _FlexibleMealLabelDialog(),
    );
    if (label == null || label.isEmpty) return;
    final saved = await widget.controller.createFlexibleMeal(
      date: date,
      label: label,
    );
    if (saved != null) await _refreshLists();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('饮食工具')),
      body: ListenableBuilder(
        listenable: widget.controller,
        builder: (context, _) => ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
          children: [
            Text('一句话记餐', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 6),
            const Text('例如：午餐吃了 150 克米饭、鸡胸肉和一份西兰花。'),
            const SizedBox(height: 12),
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
              onChanged: (value) => setState(() => _mealType = value!),
            ),
            const SizedBox(height: 10),
            TextField(
              controller: _mealText,
              minLines: 2,
              maxLines: 4,
              decoration: const InputDecoration(labelText: '描述你吃了什么'),
              onChanged: (_) => setState(() {}),
            ),
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed:
                  widget.controller.submitting || _mealText.text.trim().isEmpty
                  ? null
                  : _parseMeal,
              icon: const Icon(Icons.auto_awesome_rounded),
              label: const Text('识别营养'),
            ),
            if (_draft case final draft?) ...[
              const SizedBox(height: 12),
              AppSurface(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('约 ${draft.totals.kcal.toStringAsFixed(0)} 千卡'),
                    Text(
                      '蛋白质 ${draft.totals.proteinG.toStringAsFixed(1)}g · '
                      '碳水 ${draft.totals.carbsG.toStringAsFixed(1)}g · '
                      '脂肪 ${draft.totals.fatG.toStringAsFixed(1)}g',
                    ),
                    if (draft.questions.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text('提示：${draft.questions.join('；')}'),
                    ],
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _saveDraft,
                      child: const Text('确认记录'),
                    ),
                  ],
                ),
              ),
            ],
            const Divider(height: 38),
            Text('条码查询', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _barcode,
                    keyboardType: TextInputType.text,
                    decoration: const InputDecoration(labelText: '输入包装条码'),
                  ),
                ),
                const SizedBox(width: 10),
                FilledButton(
                  onPressed: _lookupBarcode,
                  child: const Text('查询'),
                ),
              ],
            ),
            if (_barcodeFood case final food?) ...[
              const SizedBox(height: 10),
              AppSurface(
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(food.name),
                  subtitle: Text(
                    '${food.kcal.toStringAsFixed(0)} 千卡 / ${food.basisAmountG.toStringAsFixed(0)}g',
                  ),
                  trailing: FilledButton(
                    onPressed: () => Navigator.pop(context, food),
                    child: const Text('记录'),
                  ),
                ),
              ),
            ],
            const Divider(height: 38),
            Text('吃前问一下', style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 10),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _adviceFood,
                    decoration: const InputDecoration(labelText: '食品名称'),
                  ),
                ),
                const SizedBox(width: 10),
                FilledButton(onPressed: _getAdvice, child: const Text('获取建议')),
              ],
            ),
            if (_advice case final advice?) ...[
              const SizedBox(height: 10),
              AppSurface(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(advice.recommendation),
                    if (advice.cautions.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text('注意：${advice.cautions.join('；')}'),
                    ],
                  ],
                ),
              ),
            ],
            const Divider(height: 38),
            SectionTitle(
              title: '自由餐安排',
              action: TextButton.icon(
                onPressed: _scheduleFlexibleMeal,
                icon: const Icon(Icons.add_rounded),
                label: const Text('安排'),
              ),
            ),
            if (_flexibleMeals.isEmpty)
              const Text('暂未安排自由餐')
            else
              for (final meal in _flexibleMeals)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.celebration_outlined),
                  title: Text(meal.label),
                  subtitle: Text(
                    '${meal.scheduledDate.month} 月 ${meal.scheduledDate.day} 日',
                  ),
                ),
            const Divider(height: 30),
            SectionTitle(
              title: '我的食谱',
              action: _barcodeFood == null
                  ? null
                  : TextButton(
                      onPressed: _createRecipe,
                      child: const Text('保存当前食品'),
                    ),
            ),
            const SizedBox(height: 8),
            if (_recipes.isEmpty)
              const Text('还没有保存食谱，可先从食品库记录单项食品。')
            else
              for (final recipe in _recipes)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.menu_book_outlined),
                  title: Text(recipe.name),
                  subtitle: Text(
                    '${recipe.servings.toStringAsFixed(1)} 份 · ${recipe.totals.kcal.toStringAsFixed(0)} 千卡',
                  ),
                ),
            if (widget.controller.errorMessage case final message?) ...[
              const SizedBox(height: 14),
              AppErrorCard(message: message),
            ],
          ],
        ),
      ),
    );
  }
}

class _RecipeEditorDialog extends StatefulWidget {
  const _RecipeEditorDialog({
    required this.initialName,
    required this.initialAmountG,
  });

  final String initialName;
  final double initialAmountG;

  @override
  State<_RecipeEditorDialog> createState() => _RecipeEditorDialogState();
}

class _RecipeEditorDialogState extends State<_RecipeEditorDialog> {
  late final TextEditingController _name;
  late final TextEditingController _amount;

  @override
  void initState() {
    super.initState();
    _name = TextEditingController(text: widget.initialName);
    _amount = TextEditingController(
      text: widget.initialAmountG.toStringAsFixed(0),
    );
  }

  @override
  void dispose() {
    _name.dispose();
    _amount.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('保存为食谱'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          TextField(
            controller: _name,
            decoration: const InputDecoration(labelText: '食谱名称'),
          ),
          const SizedBox(height: 10),
          TextField(
            controller: _amount,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: '食品重量（克）'),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            FocusManager.instance.primaryFocus?.unfocus();
            Navigator.pop(context, (
              _name.text.trim(),
              double.tryParse(_amount.text) ?? 0,
            ));
          },
          child: const Text('保存'),
        ),
      ],
    );
  }
}

class _FlexibleMealLabelDialog extends StatefulWidget {
  const _FlexibleMealLabelDialog();

  @override
  State<_FlexibleMealLabelDialog> createState() =>
      _FlexibleMealLabelDialogState();
}

class _FlexibleMealLabelDialogState extends State<_FlexibleMealLabelDialog> {
  final _label = TextEditingController(text: '自由餐');

  @override
  void dispose() {
    _label.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('安排自由餐'),
      content: TextField(
        controller: _label,
        autofocus: true,
        decoration: const InputDecoration(labelText: '名称'),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          onPressed: () {
            FocusManager.instance.primaryFocus?.unfocus();
            Navigator.pop(context, _label.text.trim());
          },
          child: const Text('保存'),
        ),
      ],
    );
  }
}
