#!/usr/bin/python3

import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import math
import time
import utils
import numpy
import pyopencl as cl


def get_context():
    contexts = []
    platforms = cl.get_platforms()
    for platform in platforms:
        devices = platform.get_devices()
        for device in devices:
            try:
                context = cl.Context(devices=[device])
                contexts.append(context)
            except:
                print('Can NOT create context from P(%s)-D(%s)'%(platform, device))
                continue
    return contexts[0] if len(contexts) > 0 else None

def build_program(ctx, filename):
    prog = None
    try:
        f = open(filename, 'r')
        fstr = ''.join(f.readlines())
        f.close()
        # -Werror : Make all warnings into errors.
        # https://www.khronos.org/registry/OpenCL/sdk/2.0/docs/man/xhtml/clBuildProgram.html
        prog = cl.Program(ctx, fstr).build(options=['-Werror'], cache_dir=None);
    except:
        import traceback
        traceback.print_exc()
    return prog

def create_queue(ctx):
    return cl.CommandQueue(ctx)

def create_bytearray(ctx, size):
    mf = cl.mem_flags
    py_buffer = numpy.zeros(size, dtype=numpy.int32)
    cl_buffer = cl.Buffer(ctx,
                          mf.READ_WRITE | mf.COPY_HOST_PTR,
                          hostbuf=py_buffer)
    return py_buffer, cl_buffer

def create_local_bytearray(size):
    return cl.LocalMemory(size)

def get_work_item_dimension(ctx):
    from pyopencl import context_info as ci
    from pyopencl import device_info as di
    devices = ctx.get_info(ci.DEVICES)
    assert len(devices) == 1
    dev = devices[0]
    # print('Max WI Dimensions : {}'.format(dev.get_info(di.MAX_WORK_ITEM_DIMENSIONS)))
    WGSize = dev.get_info(di.MAX_WORK_GROUP_SIZE)
    WISize = dev.get_info(di.MAX_WORK_ITEM_SIZES)

    LM = dev.get_info(di.LOCAL_MEM_SIZE)
    print('LM Size : {}'.format(LM))
    print('Max WG Size : {}'.format(WGSize))
    print('Max WI Size : {}'.format(WISize))
    return WGSize, WISize

def get_args(ctx, kernal_func_name, total_work_items):
    args = None
    py_in, dev_in = create_bytearray(ctx, total_work_items)
    py_out, dev_out = create_bytearray(ctx, total_work_items)
    if kernal_func_name == 'test_input':
        local_array_size = 8192
        args = (numpy.int32(total_work_items),
                dev_in, dev_out,
                create_local_bytearray(4 * local_array_size),
                numpy.int32(local_array_size),)
    elif kernal_func_name == 'test':
        args = (numpy.int32(total_work_items),
                dev_in, dev_out,)
    return args, (py_out, dev_out)

def evaluate(ctx, prog, queue, kernal_func_name, total_work_items, work_items_per_group, args, outs = None):

    min_time = None
    min_time_gws = None
    min_time_lws = None

    max_wgsize, wisize = get_work_item_dimension(ctx)
    assert total_work_items <= wisize[0] * wisize[1] * wisize[2]

    iter_global_WIs= int(math.log(total_work_items, 2))
    for g_factor in range(iter_global_WIs+1):
        print('=========================================== ')
        g_f_x = int(math.pow(2, g_factor))
        g_wi_size = (int(total_work_items/g_f_x), g_f_x, )
        print(' Global Work Group Size : {}'.format(g_wi_size))
        iterations = int(math.log(work_items_per_group, 2))
        for factor in range(iterations+1):
            l_f_x = int(math.pow(2, factor))
            l_wi_size = (int(work_items_per_group/l_f_x), l_f_x, )
            if l_wi_size[1] > g_wi_size[1] or l_wi_size[0] > g_wi_size[0]:
                # Local id dimensions should not exceed global dimensions.
                continue
            print('-------- ')
            print(' Local Work Group Size : {}'.format(l_wi_size))

            divided_wg_info = [int(gwi/l_wi_size[idx]) for idx, gwi in enumerate(g_wi_size)]
            print(' Divided Work Groups Info : {}'.format(divided_wg_info))
            start_time = time.perf_counter()

            caller = eval('prog.{}'.format(kernal_func_name))
            caller(queue, g_wi_size, l_wi_size, *args).wait()

            elapsed_time = time.perf_counter() - start_time
            if not min_time:
                min_time = elapsed_time
                min_time_gws = g_wi_size
                min_time_lws = l_wi_size
            else:
                if elapsed_time <= min_time:
                    min_time = elapsed_time
                    min_time_gws = g_wi_size
                    min_time_lws = l_wi_size

            if outs:
                cl.enqueue_copy(queue, outs[1], outs[0])
    print('**************************************** ')
    print(outs[0])
    print(' Best Global WI Info : {}'.format(min_time_gws))
    print(' Best Local WI Info : {}'.format(min_time_lws))
    print(' Best Elapsed Time : {}'.format(min_time))

lines = ''
def get_input():
    global lines
    data = None
    try:
        if sys.platform in ['linux', 'darwin']:
            import select
            time.sleep(0.01)
            if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
                data = sys.stdin.readline().rstrip()
        elif sys.platform == 'win32':
            import msvcrt
            time.sleep(0.01)
            if msvcrt.kbhit():
                data = msvcrt.getch().decode('utf-8')
                if data == '\r':
                    # Enter is pressed
                    data = lines
                    lines = ''
                else:
                    lines += data
                    print(data)
                    data = None
        else:
            pass
    except KeyboardInterrupt:
        data = 'exit'
    return data

if __name__ == '__main__':
    ctx = get_context()
    prog = None
    print('Enter 1 to test local memory usage')
    print('Enter 2 to test private memory usage')
    while True:
        user_input = get_input()
        if user_input == '1':
            prog = build_program(ctx, 'test_local.c')
            break
        elif user_input == '2':
            prog = build_program(ctx, 'test_private.c')
            break
        else:
            pass

    total_WorkItems = 1024
    # https://software.intel.com/sites/landingpage/opencl/optimization-guide/Work-Group_Size_Considerations.htm
    recommended_wi_per_group = 8
    kernal_func_name = 'test_input'
    args, outs = get_args(ctx, kernal_func_name, total_WorkItems)

    cwg, pwgs, lm, pm = None, None, None, None
    if ctx and prog:
        cwg, pwgs, lm, pm = utils.calculate_estimated_kernel_usage(prog, ctx, kernal_func_name)
    else:
        print('Nothing is calculated !')

    queue = create_queue(ctx)
    evaluate(ctx, prog, queue, kernal_func_name, total_WorkItems, recommended_wi_per_group, args, outs = outs)
