import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/progress/data/body_repository.dart';
import 'package:nxtrep/features/progress/presentation/navy_body_fat_sheet.dart';
import 'package:nxtrep/features/progress/presentation/progress_controller.dart';

void main() {
  testWidgets('prefills profile and previews Navy estimate before saving', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final api = ApiClient(
      config: ApiConfig(baseUri: Uri.parse('https://api.example.test/api/v1')),
      accessTokenProvider: () => 'access',
      httpClient: MockClient((request) async {
        requests.add(request);
        if (request.url.path.endsWith('/profile')) {
          return http.Response(
            jsonEncode({'sex': 'male', 'height_cm': '175'}),
            200,
          );
        }
        return http.Response(
          jsonEncode({
            'method': 'navy',
            'value_percent': '18.2',
            'range_min_percent': '15.2',
            'range_max_percent': '21.2',
            'confidence': 'medium',
            'disclaimer': 'Estimate only',
          }),
          200,
        );
      }),
    );
    addTearDown(api.close);
    final controller = ProgressController(BodyRepository(api));
    addTearDown(controller.dispose);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: NavyBodyFatSheet(controller: controller)),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('男性公式'), findsOneWidget);
    expect(
      (tester
          .widget<TextFormField>(find.byType(TextFormField).first)
          .controller
          ?.text),
      '175.0',
    );
    await tester.enterText(find.byType(TextFormField).at(1), '82');
    await tester.enterText(find.byType(TextFormField).at(2), '38');
    await tester.ensureVisible(find.text('计算估算值'));
    await tester.tap(find.text('计算估算值'));
    await tester.pumpAndSettle();

    expect(find.text('估算结果 18.2%'), findsOneWidget);
    expect(find.text('参考范围 15.2%–21.2%'), findsOneWidget);
    expect(find.text('确认保存估算值'), findsOneWidget);
    final body = jsonDecode(requests.last.body) as Map<String, dynamic>;
    expect(body['save'], isFalse);
    expect(body['waist_cm'], 82);
  });
}
