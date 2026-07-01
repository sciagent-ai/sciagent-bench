def readFoam(basepath,fileName,vars, df):
    import os
    import numpy as np

    for var in vars:
        ind = vars.index(var)
        print('reading: {}'.format(var))
        # Open the file with read only permit
        f = open(os.path.join(basepath, fileName), 'r')

        read=False
        Arr = []

        while True:
            # read line
            line = f.readline().strip('(').strip(')\n').split(' ')
            #print(line)

            if line[0] == 'internalField':
                read=True
                line = f.readline()
                line = f.readline()
            elif line[0] == '':
                continue
            elif line[0] == ';':
                break
            elif read == True:
                Arr.append([float(a) for a in line])

            # check if line is not empty
            if not line:
                break
        f.close()
        df[vars[ind]] = np.asarray(Arr)[:,ind]

