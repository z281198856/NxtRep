import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:nxtrep/core/config/api_config.dart';
import 'package:nxtrep/core/network/api_client.dart';
import 'package:nxtrep/features/agent/data/agent_repository.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/agent/presentation/agent_controller.dart';
import 'package:nxtrep/features/agent/presentation/agent_page.dart';

void main() {
  testWidgets(
    'profile card shows only supplied fields with old and new Chinese values',
    (tester) async {
      final api = ApiClient(
        config: ApiConfig(baseUri: Uri.parse('http://localhost/api/v1')),
        accessTokenProvider: () => null,
        httpClient: MockClient(
          (_) async => throw StateError('unexpected write'),
        ),
      );
      final controller = AgentController(AgentRepository(api));
      addTearDown(controller.dispose);
      addTearDown(api.close);
      controller.messages = [
        AgentMessage(
          id: 'reply',
          role: 'assistant',
          content: '请核对草稿。',
          sequence: 1,
          createdAt: DateTime(2026),
        ),
      ];
      controller.confirmations = [
        AgentConfirmationCard.fromJson({
          'confirmation_id': 'profile',
          'operation_type': 'profile_update',
          'status': 'pending',
          'version': 1,
          'impact': '已有计划和目标保留',
          'before': {
            'profile': {
              'height_cm': '170',
              'weight_kg': '70',
              'experience_level': 'beginner',
              'weekly_training_days': 3,
              'display_name': '原昵称',
              'sex': 'male',
            },
          },
          'after': {
            'changes': {
              'height_cm': '175',
              'weight_kg': '71.5',
              'experience_level': 'intermediate',
              'weekly_training_days': 4,
              'display_name': null,
            },
          },
        }),
      ];
      await tester.pumpWidget(
        MaterialApp(home: AgentPage(controller: controller)),
      );
      await tester.pumpAndSettle();
      expect(find.text('修改个人资料'), findsOneWidget);
      expect(find.text('确认修改'), findsOneWidget);
      expect(find.text('身高：170 厘米 → 175 厘米'), findsOneWidget);
      expect(find.text('体重：70 公斤 → 71.5 公斤'), findsOneWidget);
      expect(find.text('训练经验：新手 → 有一定经验'), findsOneWidget);
      expect(find.text('每周训练天数：3 天 → 4 天'), findsOneWidget);
      expect(find.text('昵称：原昵称 → 未填写'), findsOneWidget);
      expect(find.textContaining('性别：'), findsNothing);
      expect(find.text('体重会新增当前测量，历史记录保留'), findsOneWidget);
      expect(find.text('调整份量'), findsNothing);
      final changes = controller.confirmations.single.after!['changes'] as Map;
      changes['display_name'] = 'male';
      controller.notifyListeners();
      await tester.pumpAndSettle();
      expect(find.text('昵称：原昵称 → male'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
