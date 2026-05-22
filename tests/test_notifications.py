"""Tests pour le module notifications.

On ne lance pas vraiment de toast Windows / notify-send / osascript (ils
nécessitent un environnement graphique). On teste juste l'échappement XML
des inputs, qui était cassé avant v0.3.6 — un `&` dans un title brisait le
XML et le toast s'affichait silencieusement pas.
"""
from __future__ import annotations

from xml.dom.minidom import parseString

import pytest

from pzsavesync import notifications as notif


@pytest.mark.parametrize("s, must_not_break_xml", [
    ("Hello", True),
    ("Save & restore", True),
    ("Marathon <B42> avec potes", True),
    ("Apostrophe d'Alice", True),
    ('Quote "double"', True),
    ("Tout: < & > \" '", True),
    ("Pseudo & < > \" '", True),
])
def test_ps_safe_xml_produces_parseable_xml(s, must_not_break_xml):
    """Après échappement, le résultat embedded dans du XML doit parser."""
    escaped = notif._ps_safe_xml(s)
    # On essaie de parser un XML qui embed la string
    xml = f"<root><text>{escaped}</text></root>"
    doc = parseString(xml)  # lève xml.parsers.expat.ExpatError si invalide
    # On vérifie aussi que le contenu décodé matche l'original
    text_node = doc.getElementsByTagName("text")[0]
    decoded = text_node.firstChild.nodeValue if text_node.firstChild else ""
    assert decoded == s


def test_ps_safe_xml_handles_ampersand_specifically():
    """Cas qui pétait avant le fix : `&` non-échappé brisait LoadXml."""
    out = notif._ps_safe_xml("Save & restore")
    assert "&amp;" in out
    assert " & " not in out


def test_ps_safe_xml_handles_angle_brackets():
    """`<` et `>` doivent être échappés en `&lt;` / `&gt;`."""
    out = notif._ps_safe_xml("type <T>")
    assert "&lt;" in out
    assert "&gt;" in out


def test_ps_safe_xml_handles_quotes_for_strict_loadxml():
    """LoadXml() est strict — les quotes doivent être en entities aussi."""
    out = notif._ps_safe_xml("\"hi\"")
    assert "&quot;" in out
    out = notif._ps_safe_xml("'bye'")
    assert "&apos;" in out


def test_ps_safe_xml_empty_string():
    assert notif._ps_safe_xml("") == ""


def test_ps_safe_xml_unicode_passthrough():
    """Les caractères unicode (em-dash, emoji) passent inchangés."""
    s = "Push OK — bundle envoyé ✅"
    out = notif._ps_safe_xml(s)
    # Les caractères unicode "non-XML-spéciaux" ne sont pas touchés
    assert "—" in out
    assert "✅" in out


def test_notify_empty_inputs_returns_false():
    """Sanity : si rien à afficher, renvoie False sans crasher."""
    assert notif.notify("", "") is False
