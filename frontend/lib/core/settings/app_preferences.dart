import 'package:flutter/widgets.dart';

import '../../features/profile/domain/profile_models.dart';

/// Stored measurements remain kg/cm. Only presentation and user input convert.
class MeasurementUnits {
  const MeasurementUnits({this.imperial = false});

  final bool imperial;
  static const _poundsPerKg = 2.2046226218487757;
  String get weightLabel => imperial ? 'lb' : 'kg';
  String get lengthLabel => imperial ? 'in' : 'cm';
  double weight(num kg) => imperial ? kg * _poundsPerKg : kg.toDouble();
  double length(num cm) => imperial ? cm / 2.54 : cm.toDouble();
  double weightKg(num value) =>
      imperial ? value / _poundsPerKg : value.toDouble();
  double lengthCm(num value) => imperial ? value * 2.54 : value.toDouble();
  String formatWeight(num kg, {int decimals = 1}) =>
      '${weight(kg).toStringAsFixed(decimals)} $weightLabel';
  String formatLength(num cm, {int decimals = 1}) =>
      '${length(cm).toStringAsFixed(decimals)} $lengthLabel';
  String weightInput(double? kg) =>
      kg == null ? '' : weight(kg).toStringAsFixed(imperial ? 2 : 1);
  String lengthInput(double? cm) =>
      cm == null ? '' : length(cm).toStringAsFixed(imperial ? 2 : 1);

  // Saving an unchanged, rounded display must not alter the stored measurement.
  double? parseWeight(String text, {double? original}) =>
      text.trim() == weightInput(original) ? original : _parse(text, weightKg);
  double? parseLength(String text, {double? original}) =>
      text.trim() == lengthInput(original) ? original : _parse(text, lengthCm);
  double? _parse(String text, double Function(num) convert) {
    final value = double.tryParse(text.trim());
    return value == null || !value.isFinite ? null : convert(value);
  }
}

/// Above the Navigator so pushed pages and bottom sheets share account settings.
class AppPreferencesScope extends InheritedWidget {
  const AppPreferencesScope({super.key, this.settings, required super.child});

  final AppSettings? settings;
  MeasurementUnits get units =>
      MeasurementUnits(imperial: settings?.unitSystem == 'imperial');
  bool get showNoticeSummary => settings?.privacyMode == 'summary';

  static AppPreferencesScope? of(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<AppPreferencesScope>();
  static MeasurementUnits unitsOf(BuildContext context) =>
      of(context)?.units ?? const MeasurementUnits();
  static MeasurementUnits readUnits(BuildContext context) =>
      context.getInheritedWidgetOfExactType<AppPreferencesScope>()?.units ??
      const MeasurementUnits();

  @override
  bool updateShouldNotify(AppPreferencesScope oldWidget) =>
      settings != oldWidget.settings;
}
