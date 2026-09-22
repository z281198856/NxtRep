import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/network/api_exception.dart';
import '../../../core/theme/app_theme.dart';
import '../../../core/widgets/app_widgets.dart';
import '../domain/nutrition_models.dart';
import 'nutrition_controller.dart';
import 'widgets/food_line_art.dart';

class FoodLibraryPage extends StatefulWidget {
  const FoodLibraryPage({super.key, required this.controller});

  final NutritionController controller;

  @override
  State<FoodLibraryPage> createState() => _FoodLibraryPageState();
}

class _FoodLibraryPageState extends State<FoodLibraryPage> {
  final _search = TextEditingController();
  Timer? _debounce;
  List<FoodItem> _items = const [];
  FoodVisualCategory? _category;
  bool _loading = false;
  bool _searched = false;
  String? _error;

  static const _categories = <FoodVisualCategory?, String>{
    null: '全部',
    FoodVisualCategory.protein: '蛋白质',
    FoodVisualCategory.grain: '主食',
    FoodVisualCategory.vegetable: '蔬菜',
    FoodVisualCategory.fruit: '水果',
    FoodVisualCategory.dairy: '乳品',
    FoodVisualCategory.beverage: '饮品',
    FoodVisualCategory.snack: '加餐',
  };

  List<FoodItem> get _visibleItems => _category == null
      ? _items
      : _items
            .where(
              (item) => foodVisualCategory(item.name, item.brand) == _category,
            )
            .toList(growable: false);

  @override
  void initState() {
    super.initState();
    _runSearch();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 350), _runSearch);
  }

  Future<void> _runSearch() async {
    final keyword = _search.text.trim();
    setState(() {
      _loading = true;
      _searched = true;
      _error = null;
    });
    try {
      final result = await widget.controller.searchFoods(keyword);
      if (!mounted || keyword != _search.text.trim()) return;
      setState(() => _items = result.items);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _error = error.message);
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _createCustomFood() async {
    final input = await showModalBottomSheet<CustomFoodInput>(
      context: context,
      isScrollControlled: true,
      builder: (_) => const _CustomFoodSheet(),
    );
    if (input == null) return;
    final food = await widget.controller.createCustomFood(input);
    if (!mounted) return;
    if (food == null) {
      final message = widget.controller.errorMessage ?? '食品创建失败';
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
      return;
    }
    Navigator.pop(context, food);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('食品库'),
        actions: [
          IconButton(
            tooltip: '添加自定义食品',
            onPressed: _createCustomFood,
            icon: const Icon(Icons.add_rounded),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 30),
        children: [
          TextField(
            controller: _search,
            onChanged: _onChanged,
            onSubmitted: (_) => _runSearch(),
            textInputAction: TextInputAction.search,
            decoration: InputDecoration(
              labelText: '搜索食品',
              hintText: '例如：鸡胸肉、牛奶',
              prefixIcon: const Icon(Icons.search_rounded),
              suffixIcon: _loading
                  ? const Padding(
                      padding: EdgeInsets.all(14),
                      child: SizedBox.square(
                        dimension: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                    )
                  : _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: '清空',
                      onPressed: () {
                        _search.clear();
                        _runSearch();
                      },
                      icon: const Icon(Icons.close_rounded),
                    ),
            ),
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (final option in _categories.entries) ...[
                  if (option.key != _categories.keys.first)
                    const SizedBox(width: 8),
                  ChoiceChip(
                    label: Text(option.value),
                    selected: _category == option.key,
                    onSelected: (_) => setState(() => _category = option.key),
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 18),
          AppSurface(
            onTap: _createCustomFood,
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
            child: const Row(
              children: [
                Icon(
                  Icons.add_circle_outline_rounded,
                  color: AppColors.primary,
                ),
                SizedBox(width: 12),
                Expanded(child: Text('食品库里没有？添加自定义食品')),
                Icon(Icons.chevron_right_rounded, color: AppColors.muted),
              ],
            ),
          ),
          const SizedBox(height: 18),
          if (_error case final message?)
            AppErrorCard(message: message)
          else if (!_loading && _visibleItems.isEmpty)
            AppEmptyState(
              icon: Icons.no_food_rounded,
              title: _searched ? '没有找到食品' : '食品库正在准备中',
              message: '可以换个名称或分类，也可以创建自己的营养数据。',
              action: FilledButton.icon(
                onPressed: _createCustomFood,
                icon: const Icon(Icons.add_rounded),
                label: const Text('添加自定义食品'),
              ),
            )
          else ...[
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                _search.text.trim().isEmpty
                    ? '常用食品 · ${_visibleItems.length} 项'
                    : '搜索结果 · ${_visibleItems.length} 项',
                style: Theme.of(context).textTheme.titleMedium,
              ),
            ),
            ..._visibleItems.map(
              (food) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _FoodTile(
                  food: food,
                  onTap: () => Navigator.pop(context, food),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _FoodTile extends StatelessWidget {
  const _FoodTile({required this.food, required this.onTap});

  final FoodItem food;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return AppSurface(
      onTap: onTap,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      child: Row(
        children: [
          FoodLineArt(name: food.name, brand: food.brand, size: 48),
          const SizedBox(width: 13),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(food.name, style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 3),
                Text(
                  '${food.brand == null ? '' : '${food.brand} · '}每 '
                  '${food.basisAmountG.toStringAsFixed(0)} g '
                  '${food.kcal.toStringAsFixed(0)} kcal',
                  style: Theme.of(context).textTheme.labelMedium,
                ),
              ],
            ),
          ),
          const Icon(Icons.chevron_right_rounded, color: AppColors.muted),
        ],
      ),
    );
  }
}

class _CustomFoodSheet extends StatefulWidget {
  const _CustomFoodSheet();

  @override
  State<_CustomFoodSheet> createState() => _CustomFoodSheetState();
}

class _CustomFoodSheetState extends State<_CustomFoodSheet> {
  final _formKey = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _brand = TextEditingController();
  final _basis = TextEditingController(text: '100');
  final _kcal = TextEditingController();
  final _protein = TextEditingController(text: '0');
  final _carbs = TextEditingController(text: '0');
  final _fat = TextEditingController(text: '0');

  @override
  void dispose() {
    _name.dispose();
    _brand.dispose();
    _basis.dispose();
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
      CustomFoodInput(
        name: _name.text.trim(),
        brand: _brand.text.trim().isEmpty ? null : _brand.text.trim(),
        basisAmountG: double.parse(_basis.text),
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
                  '添加自定义食品',
                  style: Theme.of(context).textTheme.headlineSmall,
                ),
                const SizedBox(height: 6),
                Text(
                  '营养数据按基准份量填写，记录时会按实际克数自动换算。',
                  style: Theme.of(context).textTheme.bodyMedium
                      ?.copyWith(color: AppColors.muted),
                ),
                const SizedBox(height: 18),
                TextFormField(
                  controller: _name,
                  decoration: const InputDecoration(labelText: '食品名称'),
                  validator: (value) =>
                      value?.trim().isEmpty ?? true ? '请输入食品名称' : null,
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: _brand,
                  decoration: const InputDecoration(labelText: '品牌（可选）'),
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    Expanded(
                      child: _numberField(_basis, '基准份量（g）', positive: true),
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
                FilledButton(onPressed: _submit, child: const Text('保存并使用')),
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
