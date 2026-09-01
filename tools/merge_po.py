#!/usr/bin/env python3
"""Merge existing .po translations into a freshly regenerated .pot.

Produces updated uk.po / pl.po where:
  - every msgid present in the new .pot is kept (in .pot order),
  - existing translations from the old .po are preserved,
  - new strings get an empty msgstr (to be filled manually).

Usage: python3 merge_po.py <lang>  (lang in {uk, pl})
"""

import sys

import polib

BASE = 'addons/fayna_channel_bridge/i18n'
POT = f'{BASE}/fayna_channel_bridge.pot'


def main(lang):
    pot = polib.pofile(POT)
    old_path = f'{BASE}/{lang}.po'
    old = polib.pofile(old_path)

    # Build lookup: msgid -> (msgstr, flags, occurrences)
    old_map = {}
    for entry in old:
        old_map[entry.msgid] = entry

    new_po = polib.POFile()
    new_po.metadata = {
        'Project-Id-Version': 'Odoo Server 17.0',
        'Report-Msgid-Bugs-To': '',
        'POT-Creation-Date': pot.metadata.get('POT-Creation-Date', ''),
        'PO-Revision-Date': pot.metadata.get('POT-Creation-Date', ''),
        'Last-Translator': '',
        'Language-Team': '',
        'Language': lang,
        'MIME-Version': '1.0',
        'Content-Type': 'text/plain; charset=UTF-8',
        'Content-Transfer-Encoding': '',
        'Plural-Forms': (
            'nplurals=3; plural=(n%10==1 && n%100!=11 ? 0 : '
            'n%10>=2 && n%10<=4 && (n%100<10 || n%100>=20) ? 1 : 2);'
            if lang == 'uk'
            else 'nplurals=3; plural=(n==1 ? 0 : n%10>=2 && n%10<=4 && '
            '(n%100<10 || n%100>=20) ? 1 : 2);'
        ),
    }

    for entry in pot:
        new_entry = polib.POEntry(
            msgid=entry.msgid,
            msgid_plural=entry.msgid_plural,
            occurrences=entry.occurrences,
            flags=entry.flags,
            comment=entry.comment,
            tcomment=entry.tcomment,
        )
        old_entry = old_map.get(entry.msgid)
        if old_entry is not None and old_entry.msgstr:
            new_entry.msgstr = old_entry.msgstr
            if old_entry.msgstr_plural:
                new_entry.msgstr_plural = old_entry.msgstr_plural
        new_po.append(new_entry)

    new_po.save(f'{BASE}/{lang}.po')
    print(f'Wrote {BASE}/{lang}.po with {len(new_po)} entries')


if __name__ == '__main__':
    main(sys.argv[1])
