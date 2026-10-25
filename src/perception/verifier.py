from collections import deque, Counter

class MultiFrameVerifier:
    """ 多幀確認器與狀態合理性驗證器 """
    def __init__(self, history_size=3, match_threshold=2):
        self.history_size = history_size
        self.match_threshold = match_threshold
        self.history = deque(maxlen=history_size)

    def update(self, current_hand_cards):
        hand_key = tuple(sorted([card['name'] for card in current_hand_cards]))
        self.history.append(hand_key)

        counts = Counter(self.history)
        most_common_hand, count = counts.most_common(1)[0]
        is_stable = (count >= self.match_threshold)
        
        return {
            'is_stable': is_stable,
            'verified_hand_names': list(most_common_hand),
            'confidence_ratio': round(count / len(self.history), 2)
        }

    @staticmethod
    def validate_state(hand_cards, in_settlement=False):
        if in_settlement:
            return {'is_valid': True, 'need_recap': False, 'reasons': ["In Settlement"]}

        hand_count = len(hand_cards)
        has_low_confidence = any(card.get('low_confidence', False) for card in hand_cards)

        count_valid = hand_count in (16, 17)
        need_recap = (not count_valid) or has_low_confidence

        reasons = []
        if not count_valid:
            reasons.append(f"Invalid hand count: {hand_count}")
        if has_low_confidence:
            reasons.append("Low confidence detected in hand slots")

        return {
            'is_valid': count_valid and not has_low_confidence,
            'need_recap': need_recap,
            'reasons': reasons if reasons else ["OK"]
        }