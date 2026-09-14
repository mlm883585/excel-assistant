"""Archive licenses from the exact installed runtime packages in gui/package-lock.json."""
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]


def archive():
    gui=ROOT/'gui'; lock=json.loads((gui/'package-lock.json').read_text(encoding='utf-8'))
    target=ROOT/'vendor/licenses/gui';target.mkdir(parents=True,exist_ok=True)
    entries=[]
    for relative, package in sorted(lock['packages'].items()):
        if not relative.startswith('node_modules/') or package.get('dev') or package.get('optional'):
            continue
        installed=gui/relative
        metadata_path=installed/'package.json'
        if not metadata_path.is_file():
            raise ValueError(f'缺少安装依赖 {relative}，请先 npm ci --prefix gui')
        metadata=json.loads(metadata_path.read_text(encoding='utf-8'))
        name,version=metadata['name'],metadata['version']
        destination=target/(name.replace('/','__')+'@'+version);destination.mkdir(exist_ok=True)
        files=[]
        for path in sorted(installed.iterdir()):
            if path.is_file() and re.match(r'^(licen[sc]e|copying|notice)(\b|\.|-)',path.name,re.I):
                shutil.copyfile(path,destination/path.name);files.append(str((destination/path.name).relative_to(ROOT)).replace('\\','/'))
        if not files:
            for path in installed.iterdir():
                if path.is_file() and path.name.lower()=='readme.md' and re.search(r'^#+\s*license',path.read_text(encoding='utf-8'),re.I|re.M):
                    text=path.read_text(encoding='utf-8');match=re.search(r'^#+\s*license',text,re.I|re.M)
                    extracted=destination/'LICENSE-FROM-README.md';extracted.write_text(text[match.start():],encoding='utf-8');files.append(extracted.relative_to(ROOT).as_posix())
            # Package metadata is retained when npm omitted a standalone license.
            shutil.copyfile(metadata_path,destination/'package.json')
            supplement=ROOT/'vendor/licenses/supplements'/(name.replace('/','__')+'.txt')
            if supplement.is_file():
                shutil.copyfile(supplement,destination/'LICENSE-UPSTREAM.txt');files.append((destination/'LICENSE-UPSTREAM.txt').relative_to(ROOT).as_posix())
            if name=='@univerjs/protocol':
                shutil.copyfile(gui/'node_modules/@univerjs/core/LICENSE',destination/'LICENSE');files.append((destination/'LICENSE').relative_to(ROOT).as_posix())
        entries.append({'name':name,'version':version,'license':metadata.get('license',package.get('license','见组件元数据')),'source':metadata.get('repository',package.get('resolved','')),'files':files})
    (target/'manifest.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    missing=[e['name'] for e in entries if not e['files']]
    print(json.dumps({'packages':len(entries),'missing_license_files':missing},ensure_ascii=False))
    return entries


if __name__=='__main__':archive()
