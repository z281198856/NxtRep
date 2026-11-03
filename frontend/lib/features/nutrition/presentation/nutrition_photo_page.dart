import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:image_picker/image_picker.dart';

import '../../../core/theme/app_theme.dart';
import '../../../core/offline/form_draft.dart';
import '../domain/nutrition_models.dart';
import '../domain/nutrition_date.dart';
import 'nutrition_controller.dart';

class NutritionPhotoPage extends StatefulWidget {
  const NutritionPhotoPage({
    super.key,
    required this.controller,
    this.imageBytesPicker,
    this.recordDate,
  });

  final NutritionController controller;
  final DateTime? recordDate;
  final Future<Uint8List?> Function(ImageSource)? imageBytesPicker;

  @override
  State<NutritionPhotoPage> createState() => _NutritionPhotoPageState();
}

class _NutritionPhotoPageState extends State<NutritionPhotoPage> {
  final _picker = ImagePicker();
  late final DateTime _recordDate =
      widget.recordDate ?? widget.controller.selectedDate;
  final _formKey = GlobalKey<FormState>();
  final _notes = TextEditingController();
  String _mealType = 'lunch';
  Uint8List? _bytes;
  NutritionPhotoDraft? _draft;
  List<_PhotoItemEditor> _editors = const [];
  String? _localError;
  bool _valuesEdited = false;
  String _estimatedNotes = '';
  String? _encodedPhoto;
  bool _pickerPending = false;
  late final FormDraft _formDraft;
  String get _draftKey => 'photo:${_recordDate.toIso8601String()}';

  @override
  void initState() {
    super.initState();
    _formDraft = FormDraft(
      records: LocalRecordsScope.read(context),
      key: _draftKey,
      label: '${nutritionDateLabel(_recordDate)}餐食照片',
      fields: {'notes': _notes},
      isActive: () => mounted,
      extras: () => {
        'photo': _encodedPhoto,
        'meal': _mealType,
        'picker_pending': _pickerPending,
        'result': _draft?.toJson(),
        'estimated_notes': _estimatedNotes,
        'editors': _editors.map((e) => e.localJson()).toList(),
      },
      restoreExtras: (data) {
        _encodedPhoto = data['photo'] as String?;
        _bytes = _encodedPhoto == null ? null : base64Decode(_encodedPhoto!);
        _mealType = data['meal'] as String? ?? _mealType;
        _estimatedNotes = data['estimated_notes'] as String? ?? '';
        if (data['result'] is Map) {
          _draft = NutritionPhotoDraft.fromJson(
            Map<String, dynamic>.from(data['result'] as Map),
          );
          _editors = _draft!.items.map(_PhotoItemEditor.new).toList();
          final fields = data['editors'] as List? ?? [];
          for (var i = 0; i < _editors.length && i < fields.length; i++) {
            _editors[i].restoreLocal(
              Map<String, dynamic>.from(fields[i] as Map),
            );
          }
        }
        _pickerPending = data['picker_pending'] == true;
        _localError = '已恢复本机草稿，请核对日期、餐次和食物后继续。';
        if (_pickerPending) unawaited(_recoverPicker());
      },
      onRestored: () {
        if (mounted) setState(() {});
      },
    );
  }

  Future<void> _recoverPicker() async {
    try {
      final lost = await _picker.retrieveLostData();
      final file = lost.files?.firstOrNull;
      if (file != null) {
        final bytes = await file.readAsBytes();
        if (mounted) _replacePhoto(bytes);
      }
    } on Object {
      if (mounted) setState(() => _localError = '相机返回的照片暂不可用，已保留说明，可重新选图。');
    } finally {
      _pickerPending = false;
      _formDraft.save();
    }
  }

  void _replacePhoto(Uint8List bytes) {
    for (final editor in _editors) {
      editor.dispose();
    }
    setState(() {
      _bytes = bytes;
      _encodedPhoto = base64Encode(bytes);
      _draft = null;
      _editors = const [];
      _localError = null;
      _valuesEdited = false;
    });
    _formDraft.save();
  }

  bool get _hasNameChanges => _editors.any((editor) => editor.nameChanged);
  bool get _requiresReestimate =>
      _hasNameChanges || _notes.text.trim() != _estimatedNotes;

  double _total(double Function(_PhotoItemEditor) value) =>
      _editors.fold(0, (sum, editor) => sum + value(editor));

  @override
  void dispose() {
    _formDraft.dispose();
    _notes.dispose();
    for (final editor in _editors) {
      editor.dispose();
    }
    super.dispose();
  }

  Future<void> _pick(ImageSource source) async {
    try {
      _pickerPending = true;
      // Persist the picker destination before Android may destroy the activity.
      await LocalRecordsScope.read(context)
          ?.saveDraft(_draftKey, '${nutritionDateLabel(_recordDate)}餐食照片', {
            'notes': _notes.text,
            'photo': _encodedPhoto,
            'meal': _mealType,
            'picker_pending': true,
            'result': _draft?.toJson(),
            'estimated_notes': _estimatedNotes,
            'editors': _editors.map((e) => e.localJson()).toList(),
          });
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
      _replacePhoto(bytes);
    } on Object {
      if (!mounted) return;
      setState(() => _localError = '无法读取照片，请检查相机或相册权限后重试');
    } finally {
      _pickerPending = false;
      _formDraft.save();
    }
  }

  Future<void> _estimate() async {
    final bytes = _bytes;
    if (bytes == null) return;
    setState(() => _localError = null);
    final draft = await widget.controller.estimatePhoto(
      bytes: bytes,
      mealType: _mealType,
      eatenAt: nutritionRecordedAt(_recordDate, _mealType),
      notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
    );
    if (!mounted || draft == null) return;
    _acceptDraft(draft);
  }

  void _acceptDraft(NutritionPhotoDraft draft) {
    for (final editor in _editors) {
      editor.dispose();
    }
    setState(() {
      _draft = draft.items.isEmpty ? null : draft;
      _editors = draft.items.map(_PhotoItemEditor.new).toList();
      _valuesEdited = false;
      _estimatedNotes = _notes.text.trim();
      if (draft.items.isEmpty) _localError = '照片中没有识别到食物，请换一张清晰照片';
    });
    _formDraft.save();
  }

  Future<void> _reestimate() async {
    final draft = _draft;
    if (draft == null) return;
    if (_editors.any(
      (editor) =>
          editor.name.text.trim().isEmpty ||
          (double.tryParse(editor.amount.text) ?? 0) <= 0 ||
          (double.tryParse(editor.amount.text) ?? 0) > 99999,
    )) {
      setState(() => _localError = '请先填写食物名称和有效份量，营养值由 AI 重新估算。');
      return;
    }
    setState(() => _localError = null);
    final foodFieldsChanged = _editors.any(
      (editor) => editor.nameChanged || editor.amountChanged,
    );
    final notesOnly =
        _notes.text.trim() != _estimatedNotes && !foodFieldsChanged;
    final revised = await widget.controller.reestimatePhoto(
      draft: draft,
      reviewedFoods: notesOnly
          ? null
          : _editors.map((editor) => editor.reviewedFood()).toList(),
      notes: _notes.text.trim().isEmpty ? null : _notes.text.trim(),
    );
    // Failed correction leaves all current edits available for retry.
    if (!mounted || revised == null) return;
    if (revised.items.isEmpty) {
      setState(() => _localError = '这次没有识别到可用食物，已保留当前编辑，请修改说明后重试。');
      return;
    }
    _acceptDraft(revised);
  }

  Future<void> _save() async {
    final draft = _draft;
    if (draft == null ||
        _requiresReestimate ||
        !(_formKey.currentState?.validate() ?? false)) {
      return;
    }
    if (_editors.isEmpty) return;
    final items = _editors.map((editor) => editor.toItem()).toList();
    final saved = await widget.controller.savePhotoEntry(
      NutritionPhotoEntryInput(
        mealType: draft.mealType,
        eatenAt: draft.eatenAt,
        items: items,
        imageAssetId: draft.imageAssetId,
      ),
      draftKey: _draftKey,
    );
    if (!mounted || !saved) return;
    await clearSubmittedDraft(context, _draftKey);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          widget.controller.savedLocally
              ? '照片饮食记录已保存在本机，联网后同步'
              : '照片饮食记录已保存，营养值为估算',
        ),
      ),
    );
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
            Text('记录至 ${nutritionDateLabel(_recordDate)}'),
            const SizedBox(height: 12),
            Text(
              '选择餐次，拍照或从相册选取一张餐食照片。识别后可修改每项食物与营养值。',
              style: Theme.of(context).textTheme.bodyMedium
                  ?.copyWith(color: AppColors.muted),
            ),
            const SizedBox(height: 16),
            DropdownButtonFormField<String>(
              key: ValueKey(_mealType),
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
                  : (value) {
                      setState(() {
                        _mealType = value ?? 'lunch';
                        _draft = null;
                      });
                      _formDraft.save();
                    },
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _notes,
              enabled: !busy,
              maxLines: 2,
              maxLength: 2000,
              decoration: const InputDecoration(
                labelText: '补充说明（可选）',
                hintText: '例如：米饭一小碗，菜少油；不用填写热量',
              ),
              onChanged: (_) => setState(() => _valuesEdited = true),
            ),
            const SizedBox(height: 10),
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
                child: Image.memory(bytes, height: 220, fit: BoxFit.contain),
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
              Center(child: Text(widget.controller.photoActivity ?? '正在保存记录…')),
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
                _hasNameChanges
                    ? '菜名已修改，请按修改重新估算营养后再确认。'
                    : _requiresReestimate
                    ? '补充说明已修改，请重新估算后再确认。'
                    : _editors.any(
                        (editor) => double.tryParse(editor.kcal.text) == null,
                      )
                    ? '当前营养值尚未补齐，可按修改重新估算。'
                    : '当前待确认估算约 ${_total((editor) => double.tryParse(editor.kcal.text) ?? 0).toStringAsFixed(0)} 千卡，'
                          '食物总量约 ${_total((editor) => double.tryParse(editor.amount.text) ?? 0).toStringAsFixed(0)} 克。',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
              if (!_valuesEdited)
                Text(
                  '照片估算范围 ${draft.totals.minimum.kcal.toStringAsFixed(0)}–${draft.totals.maximum.kcal.toStringAsFixed(0)} 千卡。',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              const Text('份量、用油和菜名都可能有误差，可以先修改再确认。'),
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
                        enabled: !busy,
                        onChanged: () {
                          setState(() => _valuesEdited = true);
                          _formDraft.save();
                        },
                      ),
                      const SizedBox(height: 10),
                    ],
                  ],
                ),
              ),
              const SizedBox(height: 14),
              if (_valuesEdited || !draft.isComplete)
                OutlinedButton.icon(
                  onPressed: busy ? null : _reestimate,
                  icon: const Icon(Icons.refresh),
                  label: const Text('按修改重新估算营养'),
                ),
              FilledButton(
                onPressed: busy || _editors.isEmpty || _requiresReestimate
                    ? null
                    : _save,
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
      ) {
    for (final controller in [kcal, protein, carbs, fat]) {
      final value = double.tryParse(controller.text);
      if (value != null && original.amountG > 0) {
        _perGram[controller] = value / original.amountG;
      }
    }
  }

  final NutritionPhotoItem original;
  final TextEditingController name;
  final TextEditingController amount;
  final TextEditingController kcal;
  final TextEditingController protein;
  final TextEditingController carbs;
  final TextEditingController fat;
  final _perGram = <TextEditingController, double>{};
  bool get nameChanged => name.text.trim() != original.name;
  bool get amountChanged => double.tryParse(amount.text) != original.amountG;
  Map<String, dynamic> localJson() => {
    'name': name.text,
    'amount': amount.text,
    'kcal': kcal.text,
    'protein': protein.text,
    'carbs': carbs.text,
    'fat': fat.text,
  };
  void restoreLocal(Map<String, dynamic> data) {
    for (final entry in {
      'name': name,
      'amount': amount,
      'kcal': kcal,
      'protein': protein,
      'carbs': carbs,
      'fat': fat,
    }.entries) {
      if (data[entry.key] is String) {
        entry.value.text = data[entry.key] as String;
      }
    }
    for (final field in [kcal, protein, carbs, fat]) {
      updateNutrient(field);
    }
  }

  static String _initial(double? value) => value?.toStringAsFixed(1) ?? '';

  void updateAmount() {
    final grams = double.tryParse(amount.text);
    if (grams == null || grams <= 0) return;
    for (final entry in _perGram.entries) {
      entry.key.text = _initial(entry.value * grams);
    }
  }

  void updateNutrient(TextEditingController controller) {
    final value = double.tryParse(controller.text);
    final grams = double.tryParse(amount.text);
    if (value == null || grams == null || grams <= 0) {
      _perGram.remove(controller);
    } else {
      _perGram[controller] = value / grams;
    }
  }

  Map<String, dynamic> reviewedFood() {
    final grams = double.parse(amount.text);
    final amountChanged = grams != original.amountG;
    return {
      'name': name.text.trim(),
      'estimated_amount_g': grams,
      'amount_min_g': amountChanged ? grams : original.amountMinG,
      'amount_max_g': amountChanged ? grams : original.amountMaxG,
      'confidence': nameChanged ? 'low' : original.confidence,
      'portion_confidence': amountChanged ? 'low' : original.portionConfidence,
      'portion_basis': amountChanged
          ? '使用本次输入的份量，未验证实际称重'
          : original.portionBasis,
      'visual_evidence': nameChanged ? null : original.visualEvidence,
    };
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
  const _FoodEstimateEditor({
    required this.index,
    required this.editor,
    required this.onChanged,
    required this.enabled,
  });

  final int index;
  final _PhotoItemEditor editor;
  final VoidCallback onChanged;
  final bool enabled;

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
          Text(
            editor.original.portionBasis ?? '缺少可靠尺度，份量按照片和常见份量估计。',
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (editor.original.portionConfidence == 'low')
            Text(
              '份量把握较低，可以直接纠正。',
              style: Theme.of(context).textTheme.bodySmall,
            ),
          if (editor.original.assumptions.isNotEmpty)
            Text(
              editor.original.assumptions.first,
              style: Theme.of(context).textTheme.bodySmall,
            ),
          const SizedBox(height: 10),
          TextFormField(
            controller: editor.name,
            enabled: enabled,
            maxLength: 160,
            decoration: const InputDecoration(
              labelText: '食物名称',
              counterText: '',
            ),
            validator: (value) =>
                value == null || value.trim().isEmpty ? '请输入食物名称' : null,
            onChanged: (_) => onChanged(),
          ),
          const SizedBox(height: 10),
          _numberField(
            editor.amount,
            '份量（g）',
            max: 99999,
            onChanged: (_) {
              editor.updateAmount();
              onChanged();
            },
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _numberField(
                  editor.kcal,
                  '热量（千卡）',
                  onChanged: (_) {
                    editor.updateNutrient(editor.kcal);
                    onChanged();
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _numberField(
                  editor.protein,
                  '蛋白质（g）',
                  onChanged: (_) {
                    editor.updateNutrient(editor.protein);
                    onChanged();
                  },
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
                  onChanged: (_) {
                    editor.updateNutrient(editor.carbs);
                    onChanged();
                  },
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: _numberField(
                  editor.fat,
                  '脂肪（g）',
                  onChanged: (_) {
                    editor.updateNutrient(editor.fat);
                    onChanged();
                  },
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
    enabled: enabled,
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
