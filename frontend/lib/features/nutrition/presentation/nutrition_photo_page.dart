import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/theme/app_theme.dart';
import '../domain/nutrition_models.dart';
import 'nutrition_controller.dart';

class NutritionPhotoPage extends StatefulWidget {
  const NutritionPhotoPage({
    super.key,
    required this.controller,
    this.imageBytesPicker,
  });

  final NutritionController controller;
  final Future<Uint8List?> Function(ImageSource)? imageBytesPicker;

  @override
  State<NutritionPhotoPage> createState() => _NutritionPhotoPageState();
}

class _NutritionPhotoPageState extends State<NutritionPhotoPage> {
  final _picker = ImagePicker();
  final _formKey = GlobalKey<FormState>();
  String _mealType = 'lunch';
  Uint8List? _bytes;
  NutritionPhotoDraft? _draft;
  List<_PhotoItemEditor> _editors = const [];
  String? _localError;

  @override
  void dispose() {
    for (final editor in _editors) {
      editor.dispose();
    }
    super.dispose();
  }

  Future<void> _pick(ImageSource source) async {
    try {
      Uint8List? bytes;
      if (widget.imageBytesPicker case final picker?) {
        bytes = await picker(source);
      } else {
        final file = await _picker.pickImage(
          source: source,
          maxWidth: 2048,
          maxHeight: 2048,
          imageQuality: 85,
          requestFullMetadata: false,
        );
        if (file != null) bytes = await file.readAsBytes();
      }
      if (bytes == null) return;
      if (!mounted) return;
      for (final editor in _editors) {
        editor.dispose();
      }
      setState(() {
        _bytes = bytes;
        _draft = null;
        _editors = const [];
        _localError = null;
      });
    } on Object {
      if (!mounted) return;
      setState(() => _localError = '无法读取照片，请检查相机或相册权限后重试');
    }
  }

  Future<void> _estimate() async {
    final bytes = _bytes;
    if (bytes == null) return;
    setState(() => _localError = null);
    final draft = await widget.controller.estimatePhoto(
      bytes: bytes,
      mealType: _mealType,
    );
    if (!mounted || draft == null) return;
    for (final editor in _editors) {
      editor.dispose();
    }
    setState(() {
      _draft = draft;
      _editors = draft.items.map(_PhotoItemEditor.new).toList();
      if (draft.items.isEmpty) _localError = '照片中没有识别到食物，请换一张清晰照片';
    });
  }

  Future<void> _save() async {
    final draft = _draft;
    if (draft == null || !(_formKey.currentState?.validate() ?? false)) return;
    if (_editors.isEmpty) return;
    final items = _editors.map((editor) => editor.toItem()).toList();
    final saved = await widget.controller.savePhotoEntry(
      NutritionPhotoEntryInput(
        mealType: draft.mealType,
        eatenAt: draft.eatenAt,
        items: items,
        imageAssetId: draft.imageAssetId,
      ),
    );
    if (!mounted || !saved) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('照片饮食记录已保存，营养值为估算')));
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('拍照记一餐')),
    body: ListenableBuilder(
      listenable: widget.controller,
      builder: (context, _) {
        final busy = widget.controller.submitting;
        return ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 32),
          children: [
            Text(
              '选择餐次，拍照或从相册选取一张餐食照片。识别后可修改每项食物与营养值。',
              style: Theme.of(context).textTheme.bodyMedium
                  ?.copyWith(color: AppColors.muted),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              initialValue: _mealType,
              decoration: const InputDecoration(labelText: '餐次'),
              items: const [
                DropdownMenuItem(value: 'breakfast', child: Text('早餐')),
                DropdownMenuItem(value: 'lunch', child: Text('午餐')),
                DropdownMenuItem(value: 'dinner', child: Text('晚餐')),
                DropdownMenuItem(value: 'snack', child: Text('加餐')),
              ],
              onChanged: busy
                  ? null
                  : (value) => setState(() {
                      _mealType = value ?? 'lunch';
                      _draft = null;
                    }),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: busy ? null : () => _pick(ImageSource.camera),
                    icon: const Icon(Icons.camera_alt_outlined),
                    label: const Text('拍照'),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: busy ? null : () => _pick(ImageSource.gallery),
                    icon: const Icon(Icons.photo_library_outlined),
                    label: const Text('相册'),
                  ),
                ),
              ],
            ),
            if (_bytes case final bytes?) ...[
              const SizedBox(height: 14),
              ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Image.memory(bytes, height: 190, fit: BoxFit.cover),
              ),
              const SizedBox(height: 14),
              if (_draft == null)
                FilledButton.icon(
                  onPressed: busy ? null : _estimate,
                  icon: const Icon(Icons.auto_awesome_rounded),
                  label: const Text('识别食物并估算营养'),
                ),
            ],
            if (busy) ...[
              const SizedBox(height: 16),
              const Center(child: CircularProgressIndicator()),
              const SizedBox(height: 8),
              const Center(child: Text('正在分析照片，请稍候…')),
            ],
            if (_localError ?? widget.controller.errorMessage
                case final message?) ...[
              const SizedBox(height: 12),
              Text(
                message,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ],
            if (_draft case final draft?) ...[
              const SizedBox(height: 20),
              Text('AI 估算预览', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 6),
              Text(
                '原始估算约 ${draft.totals.estimated.kcal.toStringAsFixed(0)} 千卡（${draft.totals.minimum.kcal.toStringAsFixed(0)}–${draft.totals.maximum.kcal.toStringAsFixed(0)} 千卡）。照片难以判断份量、油和调味料，请核对后再保存。',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              if (!draft.isComplete) ...[
                const SizedBox(height: 6),
                const Text(
                  '部分食物未能完整估算，请补充或修正营养值。',
                  style: TextStyle(color: AppColors.indigo),
                ),
              ],
              if (draft.assumptions.isNotEmpty ||
                  draft.questions.isNotEmpty) ...[
                const SizedBox(height: 8),
                for (final line in [
                  ...draft.assumptions,
                  ...draft.questions,
                ].take(4))
                  Text('• $line', style: Theme.of(context).textTheme.bodySmall),
              ],
              const SizedBox(height: 12),
              Form(
                key: _formKey,
                child: Column(
                  children: [
                    for (var index = 0; index < _editors.length; index++) ...[
                      _FoodEstimateEditor(
                        index: index,
                        editor: _editors[index],
                      ),
                      const SizedBox(height: 10),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 14),
              FilledButton(
                onPressed: busy || _editors.isEmpty ? null : _save,
                child: const Text('确认食物与营养值并保存'),
              ),
              const SizedBox(height: 6),
              Text(
                '保存的是估算值，不代表精确测量。若照片无法判断，请改用食品库或手动记录。',
                style: Theme.of(context).textTheme.bodySmall
                    ?.copyWith(color: AppColors.muted),
              ),
            ],
          ],
        );
      },
    ),
  );
}

class _PhotoItemEditor {
  _PhotoItemEditor(this.original)
    : name = TextEditingController(text: original.name),
      amount = TextEditingController(text: original.amountG.toStringAsFixed(0)),
      kcal = TextEditingController(
        text: _initial(original.nutrition?.estimated.kcal),
      ),
      protein = TextEditingController(
        text: _initial(original.nutrition?.estimated.proteinG),
      ),
      carbs = TextEditingController(
        text: _initial(original.nutrition?.estimated.carbsG),
      ),
      fat = TextEditingController(
        text: _initial(original.nutrition?.estimated.fatG),
      );

  final NutritionPhotoItem original;
  final TextEditingController name;
  final TextEditingController amount;
  final TextEditingController kcal;
  final TextEditingController protein;
  final TextEditingController carbs;
  final TextEditingController fat;
  bool nutrientsEdited = false;

  static String _initial(double? value) => value?.toStringAsFixed(1) ?? '';

  void updateAmount() {
    if (nutrientsEdited || original.nutrition == null) return;
    final grams = double.tryParse(amount.text);
    if (grams == null || grams <= 0 || original.amountG <= 0) return;
    final factor = grams / original.amountG;
    final estimate = original.nutrition!.estimated;
    kcal.text = _initial(estimate.kcal * factor);
    protein.text = _initial(estimate.proteinG * factor);
    carbs.text = _initial(estimate.carbsG * factor);
    fat.text = _initial(estimate.fatG * factor);
  }

  NutritionEntryItem toItem() => NutritionEntryItem(
    name: name.text.trim(),
    amountG: double.parse(amount.text),
    basisAmountG: double.parse(amount.text),
    kcal: double.parse(kcal.text),
    proteinG: double.parse(protein.text),
    carbsG: double.parse(carbs.text),
    fatG: double.parse(fat.text),
    source: 'model_estimated',
    confidence: 'low',
  );

  void dispose() {
    name.dispose();
    amount.dispose();
    kcal.dispose();
    protein.dispose();
    carbs.dispose();
    fat.dispose();
  }
}

class _FoodEstimateEditor extends StatelessWidget {
  const _FoodEstimateEditor({required this.index, required this.editor});

  final int index;
  final _PhotoItemEditor editor;

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(14),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '食物 ${index + 1} · ${editor.original.status == 'matched' ? '食品库匹配' : '需要核对'}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 5),
          Text(
            '照片估算份量 ${editor.original.amountMinG.toStringAsFixed(0)}–${editor.original.amountMaxG.toStringAsFixed(0)} g',
            style: Theme.of(context).textTheme.bodySmall
                ?.copyWith(color: AppColors.muted),
          ),
          if (editor.original.assumptions.isNotEmpty)
            Text(
              editor.original.assumptions.first,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          const SizedBox(height: 10),
          TextFormField(
            controller: editor.name,
            maxLength: 160,
            decoration: const InputDecoration(
              labelText: '食物名称',
              counterText: '',
            ),
            validator: (value) =>
                value == null || value.trim().isEmpty ? '请输入食物名称' : null,
          ),
          const SizedBox(height: 10),
          _numberField(
            editor.amount,
            '份量（g）',
            max: 99999,
            onChanged: (_) => editor.updateAmount(),
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _numberField(
                  editor.kcal,
                  '热量（千卡）',
                  onChanged: (_) => editor.nutrientsEdited = true,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _numberField(
                  editor.protein,
                  '蛋白质（g）',
                  onChanged: (_) => editor.nutrientsEdited = true,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _numberField(
                  editor.carbs,
                  '碳水（g）',
                  onChanged: (_) => editor.nutrientsEdited = true,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _numberField(
                  editor.fat,
                  '脂肪（g）',
                  onChanged: (_) => editor.nutrientsEdited = true,
                ),
              ),
            ],
          ),
        ],
      ),
    ),
  );

  Widget _numberField(
    TextEditingController controller,
    String label, {
    double max = 100000,
    ValueChanged<String>? onChanged,
  }) => TextFormField(
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    inputFormatters: [
      FilteringTextInputFormatter.allow(RegExp(r'^\d*\.?\d{0,2}')),
    ],
    decoration: InputDecoration(labelText: label),
    onChanged: onChanged,
    validator: (value) {
      final number = double.tryParse(value?.trim() ?? '');
      return number == null ||
              number < 0 ||
              number > max ||
              (label.startsWith('份量') && number == 0)
          ? '数值无效'
          : null;
    },
  );
}
