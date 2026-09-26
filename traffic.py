import random
LEVELS=['LOW','MEDIUM','HIGH','VERY_HIGH']
def factor(level): return {'LOW':1.0,'MEDIUM':1.25,'HIGH':1.6,'VERY_HIGH':2.2}.get(level,1.0)
def simulate(edges):
    for e in edges:
        e['traffic_level']=random.choice(LEVELS); e['current_speed']=max(10,round(e['speed_limit']/factor(e['traffic_level']),1))
    return edges
