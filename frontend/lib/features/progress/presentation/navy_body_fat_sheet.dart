import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../core/theme/app_theme.dart';
import '../domain/body_models.dart';
import 'progress_controller.dart';

class NavyBodyFatSheet extends StatefulWidget {
  const NavyBodyFatSheet({super.key, required this.controller});

  final ProgressController controller;

  @override
  State<NavyBodyFatSheet> createState() => _NavyBodyFatSheetState();
}

class _NavyBodyFatSheetState extends State<NavyBodyFatSheet> {
  final _formKey = GlobalKey<FormState>();
  final _height = TextEditingController();
  final _waist = TextEditingController();
  final _neck = TextEditingController();
  final _hip = TextEditingController();
  String? _sex;
  NavyBodyFatInput? _previewInput;
  NavyBodyFatResult? _preview;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    final latest = widget.controller.measurements.isEmpty
        ? null
        : widget.controller.measurements.first;
    _waist.text = _format(latest?.waistCm);
    _neck.text = _format(latest?.neckCm);
    _hip.text = _format(latest?.hipCm);
    _loadDefaults();
  }

  String _format(double? value) => value?.toStringAsFixed(1) ?? '';

  Future<void> _loadDefaults() async {
    final defaults = await widget.controller.loadNavyDefaults();
    if (!mounted || defaults == null) return;
    setState(() {
      _sex ??= defaults.sex;
      if (_height.text.isEmpty) _height.text = _format(defaults.heightCm);
    });
  }

  @override
  void dispose() {
    _height.dispose();
    _waist.dispose();
    _neck.dispose();
    _hip.dispose();
    super.dispose();
  }

  NavyBodyFatInput? _input() {
    if (!(_formKey.currentState?.validate() ?? false) || _sex == null) {
      setState(() {});
      return null;
    }
    final waist = double.parse(_waist.text);
    final neck = double.parse(_neck.text);
    final hip = _sex == 'female' ? double.parse(_hip.text) : null;
    if (waist + (hip ?? 0) <= neck) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('请检查围度：腰围（女性加臀围）必须大于颈围')));
      return null;
    }
    return NavyBodyFatInput(
      sex: _sex!,
      heightCm: double.parse(_height.text),
      waistCm: waist,
      neckCm: neck,
      hipCm: hip,
    );
  }

  Future<void> _calculate({required bool save}) async {
    final input = save ? _previewInput : _input();
    if (input == null) return;
    setState(() => _busy = true);
    final result = await widget.controller.calculateNavy(input, save: save);
    if (!mounted) return;
    setState(() => _busy = false);
    if (result == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(widget.controller.errorMessage ?? '估算失败，请重试')),
      );
      return;
    }
    if (save) {
      Navigator.pop(context, true);
    } else {
      setState(() {
        _previewInput = input;
        _preview = result;
      });
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
    child: SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
      child: Form(
        key: _formKey,
        onChanged: () {
          if (_preview != null) {
            setState(() {
              _preview = null;
              _previewInput = null;
            });
          }
        },
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('围度估算体脂', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              '按美军围度法计算。请用软尺测量颈围和腰围；女性还需臀围。仅用于观察趋势。',
              style: Theme.of(context).textTheme.bodyMedium
                  ?.copyWith(color: AppColors.muted),
            ),
            const SizedBox(height: 18),
            DropdownButtonFormField<String>(
              key: ValueKey(_sex),
              initialValue: _sex,
              decoration: const InputDecoration(labelText: '计算公式'),
              items: const [
                DropdownMenuItem(value: 'male', child: Text('男性公式')),
                DropdownMenuItem(value: 'female', child: Text('女性公式')),
              ],
              onChanged: (value) => setState(() {
                _sex = value;
                _preview = null;
                _previewInput = null;
              }),
              validator: (value) => value == null ? '请选择计算公式' : null,
            ),
            const SizedBox(height: 12),
            _field(_height, '身高（cm）', 300),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(child: _field(_waist, '腰围（cm）', 400)),
                const SizedBox(width: 10),
                Expanded(child: _field(_neck, '颈围（cm）', 200)),
              ],
            ),
            if (_sex == 'female') ...[
              const SizedBox(height: 12),
              _field(_hip, '臀围（cm）', 400),
            ],
            const SizedBox(height: 10),
            Text(
              '已预填最近一次身体记录中的围度；请核对是否为本次测量。',
              style: Theme.of(context).textTheme.bodySmall
                  ?.copyWith(color: AppColors.muted),
            ),
            if (_preview case final result?) ...[
              const SizedBox(height: 18),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: AppColors.indigoSoft,
                  borderRadius: BorderRadius.circular(16),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      '估算结果 ${result.valuePercent.toStringAsFixed(1)}%',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '参考范围 ${result.rangeMinPercent.toStringAsFixed(1)}%–${result.rangeMaxPercent.toStringAsFixed(1)}%',
                    ),
                    Text(
                      result.disclaimer,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                  ],
                ),
              ),
            ],
            const SizedBox(height: 18),
            FilledButton(
              onPressed: _busy
                  ? null
                  : () => _calculate(save: _preview != null),
              child: _busy
                  ? const SizedBox(
                      height: 20,
                      width: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : Text(_preview == null ? '计算估算值' : '确认保存估算值'),
            ),
          ],
        ),
      ),
    ),
  );

  TextFormField _field(
    TextEditingController controller,
    String label,
    double max,
  ) => TextFormField(
    controller: controller,
    keyboardType: const TextInputType.numberWithOptions(decimal: true),
    inputFormatters: [
      FilteringTextInputFormatter.allow(RegExp(r'^\d*\.?\d{0,2}')),
    ],
    decoration: InputDecoration(labelText: label),
    validator: (text) {
      final value = double.tryParse(text?.trim() ?? '');
      return value == null || value <= 0 || value > max ? '请输入有效数值' : null;
    },
  );
}
