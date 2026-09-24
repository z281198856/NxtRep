import 'package:flutter_test/flutter_test.dart';
import 'package:nxtrep/features/agent/domain/agent_models.dart';
import 'package:nxtrep/features/nutrition/domain/nutrition_models.dart';
import 'package:nxtrep/features/training/domain/training_models.dart';

void main() {
  group('new end-to-end capability models', () {
    test('serializes the pre-workout check accepted by the backend', () {
      const input = PreWorkoutCheckInput(
        sleepQuality: 4,
        energy: 3,
        availableMinutes: 45,
      );

      expect(input.toJson(), {
        'sleep_quality': 4,
        'energy': 3,
        'pain': const <Object>[],
        'available_minutes': 45,
      });
    });

    test('parses a calendar adjustment draft with decimal values', () {
      final draft = CalendarAdjustmentDraft.fromJson({
        'id': 'draft-1',
        'strategy': 'shift',
        'duration_change_minutes': -15,
        'volume_change_percent': '-10.5',
        'warnings': ['连续训练天数增加'],
        'version': 2,
      });

      expect(draft.strategy, 'shift');
      expect(draft.durationChangeMinutes, -15);
      expect(draft.volumeChangePercent, -10.5);
      expect(draft.warnings, ['连续训练天数增加']);
    });

    test('parses managed conversations and long-term memories', () {
      final conversation = AgentConversation.fromJson({
        'id': 'conversation-1',
        'title': '增肌计划',
        'status': 'active',
        'summary': '讨论每周三练',
        'last_message_at': '2026-09-24T10:00:00Z',
        'version': 3,
      });
      final memory = AgentMemory.fromJson({
        'id': 'memory-1',
        'category': 'equipment',
        'content': '家里只有可调哑铃',
        'source': 'user',
        'saved_at': '2026-09-24T10:00:00Z',
        'version': 1,
      });

      expect(conversation.title, '增肌计划');
      expect(conversation.summary, '讨论每周三练');
      expect(memory.category, 'equipment');
      expect(memory.content, '家里只有可调哑铃');
    });

    test('parses intelligent meal drafts and flexible meals', () {
      final draft = NutritionTextDraft.fromJson({
        'id': 'meal-draft-1',
        'meal_type': 'lunch',
        'totals': {
          'kcal': '520.0',
          'protein_g': '42.5',
          'carbs_g': '61.0',
          'fat_g': '12.0',
        },
        'missing_items': <String>[],
        'questions': ['鸡胸肉是否去皮？'],
        'version': 1,
      });
      final flexibleMeal = FlexibleMeal.fromJson({
        'id': 'flex-1',
        'scheduled_date': '2026-09-26',
        'label': '朋友聚餐',
        'notes': null,
        'version': 1,
      });

      expect(draft.totals.kcal, 520);
      expect(draft.totals.proteinG, 42.5);
      expect(draft.questions, ['鸡胸肉是否去皮？']);
      expect(flexibleMeal.label, '朋友聚餐');
      expect(flexibleMeal.scheduledDate.day, 26);
    });
  });
}
