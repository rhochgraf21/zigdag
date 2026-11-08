from zigdag import verifies
from zigdag.core.findings import Result
from zigdag.core.language.lexicons import LexiconName
from zigdag.core.settings import read_settings


@verifies("zigdag.core.settings#read")
def test_settings_are_read_with_their_problems():
    settings, problems = read_settings('[settings]\nruleset = 1\n[adapters]\ndefault = "python"\n'
                                       '[lexicon.vague-words]\nremove = ["fast"]\n')
    assert not problems and settings.default_adapter == "python"
    assert settings.lexicon[LexiconName.VAGUE_WORDS] == ((), ("fast",))
    _, problems = read_settings("[settings]\nruleset = 2\n[nonsense]\n")
    says = [p.say for p in problems if p.result is Result.BREAKS]
    assert any("rule set 1" in s for s in says) and any("unknown section" in s for s in says)
