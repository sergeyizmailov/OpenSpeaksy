from transcriber import Transcriber


class StubTranscriber(Transcriber):
    def __init__(self, text):
        self.text = text

    def _transcribe_mistral(self, wav_path, language=None):
        return self.text


def test_intentionally_repeated_sentences_are_preserved():
    text = (
        "Спасибо за помощь. Спасибо за помощь. "
        "Эту строку нужно оставить два раза. Эту строку нужно оставить два раза."
    )

    result = StubTranscriber(text).transcribe_wav_sync("unused.wav", backend="mistral")

    assert result == text + " "
