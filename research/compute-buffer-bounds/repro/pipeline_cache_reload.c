#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <vulkan/vulkan.h>
int main(int c,char**v){
 int push=atoi(v[2]);
 void*h=dlopen(v[1],RTLD_NOW); PFN_vkGetInstanceProcAddr gipa=dlsym(h,"vkGetInstanceProcAddr");
 #define G(n) PFN_##n n=(PFN_##n)gipa(inst,#n)
 VkInstance inst=0; G(vkCreateInstance);
 VkApplicationInfo ai={VK_STRUCTURE_TYPE_APPLICATION_INFO,0,"t",0,"t",0,VK_API_VERSION_1_3};
 VkInstanceCreateInfo ici={VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,0,0,&ai};
 vkCreateInstance(&ici,0,&inst);
 G(vkEnumeratePhysicalDevices);G(vkCreateDevice);G(vkGetDeviceProcAddr);
 uint32_t n=1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(inst,&n,&pd);
 float pr=1; VkDeviceQueueCreateInfo q={VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,0,0,0,1,&pr};
 const char* ex[]={"VK_KHR_push_descriptor","VK_KHR_portability_subset"};
 VkDeviceCreateInfo dci={VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,0,0,1,&q,0,0,2,ex};
 VkDevice d; VkResult r=vkCreateDevice(pd,&dci,0,&d); if(r){printf("dev %d\n",r);return 1;}
 #define D(n) PFN_##n n=(PFN_##n)vkGetDeviceProcAddr(d,#n)
 D(vkCreateDescriptorSetLayout);D(vkCreatePipelineLayout);D(vkCreateShaderModule);D(vkCreateComputePipelines);
 VkDescriptorSetLayoutBinding b[37];
 for(int i=0;i<37;i++){b[i]=(VkDescriptorSetLayoutBinding){i,i<6?VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER:VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1,VK_SHADER_STAGE_COMPUTE_BIT,0};}
 VkDescriptorSetLayoutCreateInfo lci={VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO,0,push?VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR:0,37,b};
 VkDescriptorSetLayout dsl; r=vkCreateDescriptorSetLayout(d,&lci,0,&dsl); if(r){printf("dsl %d\n",r);return 1;}
 VkPushConstantRange pcr={VK_SHADER_STAGE_COMPUTE_BIT,0,16};
 VkPipelineLayoutCreateInfo plci={VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,0,0,1,&dsl,1,&pcr};
 VkPipelineLayout pl; vkCreatePipelineLayout(d,&plci,0,&pl);
 FILE*f=fopen("t.spv","rb"); fseek(f,0,2); long sz=ftell(f); rewind(f); char*code=malloc(sz); fread(code,1,sz,f);
 VkShaderModuleCreateInfo smci={VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,0,0,sz,(uint32_t*)code};
 VkShaderModule sm; vkCreateShaderModule(d,&smci,0,&sm);
 VkComputePipelineCreateInfo cci={VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO,0,0,{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,0,0,VK_SHADER_STAGE_COMPUTE_BIT,sm,"main"},pl};
 D(vkCreatePipelineCache);D(vkGetPipelineCacheData);
 void*ini=0; size_t inisz=0;
 if(c>3 && strcmp(v[3],"-")){FILE*g=fopen(v[3],"rb"); fseek(g,0,2); inisz=ftell(g); rewind(g); ini=malloc(inisz); fread(ini,1,inisz,g); fclose(g);}
 VkPipelineCacheCreateInfo pcci={VK_STRUCTURE_TYPE_PIPELINE_CACHE_CREATE_INFO,0,0,inisz,ini};
 VkPipelineCache cache=0; VkResult cr=vkCreatePipelineCache(d,&pcci,0,&cache); fprintf(stderr,"=== pipeline cache from %zu bytes: vkCreatePipelineCache=%d handle=%p\n",inisz,cr,(void*)cache); if(cr) cache=0;
 fprintf(stderr,"=== creating pipeline\n");
 VkPipeline p; r=vkCreateComputePipelines(d,cache,1,&cci,0,&p);
 if(c>4 && cache){size_t n2=0; vkGetPipelineCacheData(d,cache,&n2,0); void*buf=malloc(n2); vkGetPipelineCacheData(d,cache,&n2,buf); FILE*g=fopen(v[4],"wb"); fwrite(buf,1,n2,g); fclose(g); fprintf(stderr,"=== saved %zu bytes\n",n2);}
 printf("RESULT push=%d vkCreateComputePipelines=%d\n",push,r); return 0;}
