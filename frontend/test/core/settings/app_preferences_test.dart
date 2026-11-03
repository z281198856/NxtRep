import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/core/settings/app_preferences.dart';
import 'package:nxtrep/features/profile/domain/profile_models.dart';

AppSettings preferences(String units) => AppSettings(
  unitSystem: units,
  timezone: 'Asia/Shanghai',
  privacyMode: 'private',
  shareAnonymousAnalytics: false,
  version: 1,
);

void main() {
  test('imperial input converts to canonical units without rounding unchanged records', () {
    const units = MeasurementUnits(imperial: true);
    expect(units.weight(1), closeTo(2.2046226218487757, 1e-12));
    expect(units.length(2.54), 1);
    expect(units.parseWeight('154'), closeTo(69.85322498, 1e-7));
    expect(units.parseLength('70'), 177.8);
    expect(
      units.parseWeight(units.weightInput(70.1234), original: 70.1234),
      70.1234,
    );
    expect(
      units.parseLength(units.lengthInput(178.1234), original: 178.1234),
      178.1234,
    );
    expect(units.parseWeight(''), isNull);
    expect(units.parseWeight('NaN'), isNull);
  });

  testWidgets(
    'account preference changes reach a pushed route and reset on logout',
    (tester) async {
      final settings = ValueNotifier<AppSettings?>(preferences('metric'));
      addTearDown(settings.dispose);
      await tester.pumpWidget(
        ValueListenableBuilder<AppSettings?>(
          valueListenable: settings,
          builder: (_, value, _) => AppPreferencesScope(
            settings: value,
            child: MaterialApp(
              home: Builder(
                builder: (context) => Scaffold(
                  body: TextButton(
                    onPressed: () => Navigator.of(context).push(
                      MaterialPageRoute<void>(
                        builder: (context) => Scaffold(
                          body: Text(
                            AppPreferencesScope.unitsOf(context)
                                .formatWeight(70),
                          ),
                        ),
                      ),
                    ),
                    child: const Text('打开'),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      expect(find.text('70.0 kg'), findsOneWidget);
      settings.value = preferences('imperial');
      await tester.pumpAndSettle();
      expect(find.text('154.3 lb'), findsOneWidget);
      settings.value = null;
      await tester.pumpAndSettle();
      expect(find.text('70.0 kg'), findsOneWidget);
    },
  );
}
