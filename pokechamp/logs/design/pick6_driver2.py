import json, subprocess, os
os.chdir('/home/user/junichi123456.github.io/pokechamp/tool')
OUT='../logs/design/'
def key(item):
    v=[x[0] for x in item[1].values()]; return (min(v), sum(v)/len(v))
def rank(depth):
    d=json.load(open(f'{OUT}pick6_d{depth}.json',encoding='utf-8'))
    return [c for c,_ in sorted([(c,p) for c,p in d.items() if c!='(核5体のみ)'], key=key, reverse=True)]
def save(msg):
    subprocess.run('cd /home/user/junichi123456.github.io && git add -A && git commit -qm "%s\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\nClaude-Session: https://claude.ai/code/session_017zF5X5Hhgg74J4upn1xuNA" && git pull -q --rebase origin ccr-22f85824-zkfyfy && git push -q -u origin ccr-22f85824-zkfyfy' % msg, shell=True)
def run(depth, only, tag, custom='こうごうせい'):
    cmd=['python3','megapick.py','--all','--gusoku','--depth',str(depth),'--seed',tag,'--out','pick6','--only',','.join(only),'--custom',custom]
    subprocess.run(cmd, stdout=open(f'/tmp/pick6_d{depth}.log','w'), stderr=subprocess.STDOUT)
top=[c for c in rank(1) if c!='グソクムシャ'][:10]
print('d1 top10',top,flush=True)
run(2,top+['メガニウム'],'p2'); save('6枠目の選定: 深さ2の結果を保存')
r2=[c for c in rank(2) if c!='メガニウム'][:4]
print('d2 top4',r2,'meganium rank',rank(2).index('メガニウム')+1,flush=True)
run(3,r2+['メガニウム'],'p3'); save('6枠目の選定: 深さ3の結果を保存')
print('done',flush=True)
