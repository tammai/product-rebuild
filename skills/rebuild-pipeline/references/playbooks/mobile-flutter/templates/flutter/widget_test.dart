import 'package:[[app_name]]/main.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('the app builds', (tester) async {
    await tester.pumpWidget(const ProviderScope(child: App()));
    expect(find.text('[[app_name]]'), findsOneWidget);
  });
}
